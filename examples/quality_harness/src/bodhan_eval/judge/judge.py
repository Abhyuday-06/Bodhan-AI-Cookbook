"""LLM Judge orchestrator and consistency evaluator."""

from __future__ import annotations

import logging

from bodhan_eval.api.llm import LLMJudgeClient
from bodhan_eval.judge.rubric import JUDGE_SYSTEM_PROMPT, build_judge_prompt
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)


class JudgeOrchestrator:
    """Orchestrates LLM-as-a-judge quality evaluations."""

    def __init__(self, llm_client: LLMJudgeClient | None):
        self.llm_client = llm_client

    async def judge_item(
        self,
        item: DatasetItem,
        translation: str,
        prior_checks: list[CheckResult] | None = None,
    ) -> list[CheckResult]:
        """Run the LLM judge on an item and parse structured error flags."""
        if not self.llm_client or not self.llm_client.api_key:
            return []

        user_prompt = build_judge_prompt(
            source=item.source,
            translation=translation,
            lang=item.lang,
            automated_findings=prior_checks,
        )

        try:
            verdict = await self.llm_client.judge(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(f"LLM judge query failed for item {item.id}: {e}")
            return []

        if not verdict or "errors" not in verdict:
            return []

        results: list[CheckResult] = []
        raw_errors = verdict.get("errors", [])
        if not isinstance(raw_errors, list):
            return []

        for err in raw_errors:
            if not isinstance(err, dict):
                continue

            cat_str = str(err.get("category", "")).lower()
            try:
                error_type = ErrorCategory(cat_str)
            except ValueError:
                # Default to mistranslation if category is not recognized
                error_type = ErrorCategory.MISTRANSLATION

            sev_str = str(err.get("severity", "major")).lower()
            try:
                severity = Severity(sev_str)
            except ValueError:
                severity = Severity.MAJOR

            span_data = err.get("span")
            span = None
            if isinstance(span_data, (list, tuple)) and len(span_data) == 2:
                try:
                    span = (int(span_data[0]), int(span_data[1]))
                except (ValueError, TypeError):
                    span = None

            evidence = str(err.get("evidence") or err.get("explanation") or "Flagged by LLM Judge")
            confidence = float(err.get("confidence", 0.85))
            confidence = max(0.0, min(1.0, confidence))

            results.append(
                CheckResult(
                    check_name="llm_judge",
                    passed=False,
                    error_type=error_type,
                    severity=severity,
                    span=span,
                    evidence=evidence,
                    confidence=confidence,
                    details={"explanation": err.get("explanation", "")},
                )
            )

        return results

    async def measure_consistency(
        self,
        item: DatasetItem,
        translation: str,
        n_runs: int = 3,
        *,
        prior_checks: list[CheckResult] | None = None,
    ) -> float | None:
        """
        Evaluate judge consistency across n separate runs on the same item.
        Target: >= 90% category agreement.
        """
        if n_runs < 2:
            raise ValueError("Consistency requires at least two judge runs")
        if not self.llm_client or not self.llm_client.api_key:
            return None

        user_prompt = build_judge_prompt(item.source, translation, item.lang, prior_checks)
        verdicts = []
        for _ in range(n_runs):
            res = await self.llm_client.judge(
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.0,
                use_cache=False,
            )
            errors = res.get("errors") if isinstance(res, dict) else None
            if not isinstance(errors, list) or any(
                not isinstance(error, dict) or not isinstance(error.get("category"), str) for error in errors
            ):
                return None
            verdicts.append(tuple(sorted(error["category"] for error in errors)))

        # Check fraction of runs agreeing with majority verdict
        majority_count = max(verdicts.count(v) for v in verdicts)
        return majority_count / float(n_runs)
