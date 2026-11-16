"""Main evaluation orchestrator coordinating checks, models, judge, and reports."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from bodhan_eval.api.llm import LLMJudgeClient
from bodhan_eval.api.speak import SpeakClient
from bodhan_eval.api.transcribe import TranscribeClient
from bodhan_eval.api.translate import TranslateClient
from bodhan_eval.cache import DiskCache
from bodhan_eval.checks import (
    AudioAnalysisCheck,
    BackTranslationCheck,
    EntityCheck,
    FormatCheck,
    NumberCheck,
    ReferenceCheck,
    ScriptCheck,
    SpeechCheck,
)
from bodhan_eval.concurrency import AsyncRateLimiter, CostTracker
from bodhan_eval.config import Config
from bodhan_eval.dataset import filter_by_langs, read_dataset
from bodhan_eval.judge.calibration import Calibrator
from bodhan_eval.judge.judge import JudgeOrchestrator
from bodhan_eval.report.calibration_report import generate_calibration_json
from bodhan_eval.report.diff import generate_diff_md
from bodhan_eval.report.items import generate_items_jsonl
from bodhan_eval.report.summary import generate_summary_json, generate_summary_md
from bodhan_eval.types import CheckResult, DatasetItem, ItemReport, Severity

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates the entire evaluation harness workflow across all phases."""

    def __init__(self, config: Config):
        self.config = config
        self.cache = DiskCache(config.cache_dir)
        self.cost_tracker = CostTracker(max_cost_inr=config.max_cost_inr)
        self.rate_limiter = AsyncRateLimiter(max_concurrent=config.concurrency)

        # Initialize API clients
        self.translate_client: TranslateClient | None = None
        if config.bodhan_translate_key:
            self.translate_client = TranslateClient(
                api_key=config.bodhan_translate_key,
                base_url=config.bodhan_api_base,
                cache=self.cache,
                cost_tracker=self.cost_tracker,
                rate_limiter=self.rate_limiter,
            )

        self.speak_client: SpeakClient | None = None
        if config.bodhan_speak_key:
            self.speak_client = SpeakClient(
                api_key=config.bodhan_speak_key,
                base_url=config.bodhan_api_base,
                cache=self.cache,
                cost_tracker=self.cost_tracker,
                rate_limiter=self.rate_limiter,
            )

        self.transcribe_client: TranscribeClient | None = None
        if config.bodhan_transcribe_key:
            self.transcribe_client = TranscribeClient(
                api_key=config.bodhan_transcribe_key,
                base_url=config.bodhan_api_base,
                cache=self.cache,
                cost_tracker=self.cost_tracker,
                rate_limiter=self.rate_limiter,
            )

        self.llm_client: LLMJudgeClient | None = None
        if config.llm_api_key:
            self.llm_client = LLMJudgeClient(
                base_url=config.llm_base_url,
                model=config.llm_model,
                api_key=config.llm_api_key,
                cache=self.cache,
                rate_limiter=self.rate_limiter,
            )

        self.judge_orchestrator = JudgeOrchestrator(self.llm_client)

        # Instantiate check modules
        self.script_check = ScriptCheck()
        self.format_check = FormatCheck()
        self.number_check = NumberCheck()
        self.entity_check = EntityCheck()
        self.reference_check = ReferenceCheck()
        self.audio_check = AudioAnalysisCheck()
        self.backtranslation_check = BackTranslationCheck()
        self.speech_check = SpeechCheck()

    def _calculate_item_score(self, flags: list[CheckResult]) -> float:
        """MQM-style severity penalty scoring."""
        penalty = 0.0
        for f in flags:
            if not f.passed:
                sev = f.severity or Severity.MAJOR
                if sev == Severity.MINOR:
                    penalty += 0.5
                elif sev == Severity.MAJOR:
                    penalty += 2.0
                elif sev == Severity.CRITICAL:
                    penalty += 5.0
        return max(0.0, round(10.0 - penalty, 2))

    async def _generate_missing_outputs(self, items: list[DatasetItem], out_dir: Path) -> None:
        """Synthesize missing translations and audio files when --generate is set."""
        audio_dir = out_dir / "generated_audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        for item in items:
            # 1. Generate missing translation via Indic-Translate
            if not item.translation and self.translate_client:
                try:
                    logger.info(f"Generating translation for {item.id} ({item.lang})...")
                    item.translation = await self.translate_client.translate(
                        text=item.source,
                        target_lang=item.lang,
                    )
                except Exception as e:
                    logger.error(f"Failed to generate translation for {item.id}: {e}")

            # 2. Generate missing speech via Indic-Speak
            if not item.audio and item.translation and self.speak_client:
                if not self.cost_tracker.is_over_budget():
                    try:
                        audio_file = audio_dir / f"{item.id}.{item.lang}.wav"
                        logger.info(f"Synthesizing speech for {item.id} ({item.lang})...")
                        await self.speak_client.synthesize(
                            text=item.translation,
                            lang=item.lang,
                            output_path=audio_file,
                        )
                        item.audio = str(audio_file)
                    except Exception as e:
                        logger.error(f"Failed to generate speech for {item.id}: {e}")

    async def _evaluate_single_item(self, item: DatasetItem) -> ItemReport:
        """Run all applicable checks on a single item."""
        checks_run: list[str] = []
        flags: list[CheckResult] = []
        translation = item.translation or ""

        # Phase 1: Deterministic Free Checks
        for chk in [self.script_check, self.format_check, self.number_check, self.entity_check]:
            checks_run.append(chk.name)
            res = await chk.run(item, translation, item.lang)
            flags.extend(res)

        if item.reference:
            checks_run.append(self.reference_check.name)
            res = await self.reference_check.run(item, translation, item.lang)
            flags.extend(res)

        if item.audio:
            checks_run.append(self.audio_check.name)
            res = await self.audio_check.run(item, translation, item.lang)
            flags.extend(res)

        # Phase 2: Round-Trip Back-Translation Check
        if self.translate_client and translation and not self.cost_tracker.is_over_budget():
            checks_run.append(self.backtranslation_check.name)
            res = await self.backtranslation_check.run(
                item, translation, item.lang, translate_client=self.translate_client
            )
            flags.extend(res)

        # Phase 3: Speech Quality Check (Selective on audio)
        if self.transcribe_client and item.audio and not self.cost_tracker.is_over_budget():
            checks_run.append(self.speech_check.name)
            res = await self.speech_check.run(
                item, translation, item.lang, transcribe_client=self.transcribe_client
            )
            flags.extend(res)

        # Phase 4: LLM Judge (with prior findings context)
        if self.llm_client and translation:
            checks_run.append("llm_judge")
            judge_res = await self.judge_orchestrator.judge_item(
                item, translation, prior_checks=flags
            )
            flags.extend(judge_res)

        # Compute item quality score
        score = self._calculate_item_score(flags)

        return ItemReport(
            id=item.id,
            lang=item.lang,
            source=item.source,
            translation=item.translation,
            audio=item.audio,
            reference=item.reference,
            checks_run=checks_run,
            flags=flags,
            score=score,
        )

    async def run(self) -> None:
        """Execute the full evaluation pipeline."""
        start_time = time.time()
        logger.info(f"Starting Bodhan Quality Evaluation Harness on {self.config.dataset}")
        self.config.validate_api_access()

        out_path = Path(self.config.out).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

        # 1. Load Dataset
        raw_items, skipped = read_dataset(self.config.dataset)
        items = filter_by_langs(raw_items, self.config.target_langs)
        logger.info(f"Loaded {len(items)} items matching target languages: {self.config.target_langs}")

        if not items:
            logger.error("No items matching target languages found. Exiting.")
            return

        # 2. Generate Missing Content if requested
        if self.config.generate:
            logger.info("Executing --generate for missing translations and audio...")
            await self._generate_missing_outputs(items, out_path)

        # 3. Run Evaluations Concurrently
        logger.info("Executing evaluation checks across items...")
        tasks = [self._evaluate_single_item(item) for item in items]
        reports: list[ItemReport] = await asyncio.gather(*tasks)

        # 4. Calibration against Ground Truth (if provided)
        calibration_report = None
        if self.config.calibration:
            logger.info(f"Calibrating harness against ground truth: {self.config.calibration}")
            calibrator = Calibrator()
            try:
                gold_labels = calibrator.load_labels(self.config.calibration)
                predictions = {r.id: r.flags for r in reports}
                clean_ids = {r.id for r in reports if not r.flags}

                # Initial calibration
                calibration_report = calibrator.calibrate(predictions, gold_labels, clean_ids)
                # Tune thresholds dynamically
                tuned_thresholds = calibrator.tune_thresholds(predictions, gold_labels)
                calibration_report = calibrator.calibrate(
                    predictions, gold_labels, clean_ids, confidence_thresholds=tuned_thresholds
                )

                # Filter flags with calibrated thresholds
                for r in reports:
                    r.flags = [
                        f for f in r.flags
                        if f.confidence >= tuned_thresholds.get(f.error_type.value if f.error_type else "default", 0.30)
                    ]
                    r.score = self._calculate_item_score(r.flags)

                logger.info(
                    f"Calibration complete: Precision={calibration_report.overall_precision:.2f}, "
                    f"Recall={calibration_report.overall_recall:.2f}, F1={calibration_report.overall_f1:.2f}"
                )
            except Exception as e:
                logger.error(f"Calibration failed: {e}")

        # 5. Generate Reports
        logger.info(f"Writing evaluation artifacts to {out_path}...")
        cost_info = self.cost_tracker.summary()

        # Write items.jsonl
        generate_items_jsonl(reports, out_path / "items.jsonl")

        # Write summary.json
        summary_json = generate_summary_json(reports, calibration_report, cost_info)
        (out_path / "summary.json").write_text(
            json.dumps(summary_json, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Write summary.md
        config_dict = {
            "dataset": self.config.dataset,
            "langs": self.config.langs,
            "generate": self.config.generate,
            "baseline": self.config.baseline,
        }
        summary_md = generate_summary_md(reports, calibration_report, cost_info, config_dict)
        (out_path / "summary.md").write_text(summary_md, encoding="utf-8")

        # Write calibration.json
        if calibration_report:
            generate_calibration_json(calibration_report, out_path / "calibration.json")

        # Write diff.md if baseline supplied
        if self.config.baseline:
            logger.info(f"Comparing run against baseline at {self.config.baseline}...")
            diff_content = generate_diff_md(out_path, self.config.baseline)
            (out_path / "diff.md").write_text(diff_content, encoding="utf-8")

        elapsed = time.time() - start_time
        logger.info(
            f"Evaluation finished in {elapsed:.1f}s. "
            f"Spend: ₹{cost_info['total_cost_inr']:.4f} / ₹{self.config.max_cost_inr:.2f}. "
            f"Cache hit rate: {self.cache.stats.hit_rate * 100:.1f}%."
        )
