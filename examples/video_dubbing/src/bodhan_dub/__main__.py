"""Command line for translating and dubbing an English video."""
from __future__ import annotations

import argparse
import logging
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from time import monotonic

import yaml
from dotenv import load_dotenv

from .media import (
    ASR_RATE,
    MIX_RATE,
    cut_wave,
    decode_track,
    frame_activity,
    mix_track,
    mux,
    probe,
    sample_index,
    speech_spans,
    srt_timestamp,
    wave_bytes,
)
from .providers import KNOWN_VOICES, VOICES, DubError, Providers, log, put_bytes, put_json, safe_error
from .workflow import plan_glossary, render_segment, transcribe_window

ALLOWED = {".mp4", ".mov", ".mkv", ".webm"}


def yaml_mapping(path):
    if not path:
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DubError(f"could not read {path.name} as YAML") from exc
    if not isinstance(value, dict):
        raise DubError(f"{path.name} must be a YAML mapping")
    return value


def voice_settings(path, languages):
    config = yaml_mapping(path)
    result = {}
    for language in languages:
        voice = config.get(language, VOICES[language][0])
        if isinstance(voice, dict):
            voice = voice.get("voice")
        if not isinstance(voice, str) or voice not in KNOWN_VOICES:
            raise DubError(f"unknown Indic-Speak voice for {language}")
        result[language] = voice
    return result


def glossary_settings(path):
    glossary = yaml_mapping(path)
    clean = {}
    for term, options in glossary.items():
        if not isinstance(term, str) or not term.strip():
            raise DubError("glossary term must be a nonempty string")
        term = term.strip()
        if isinstance(options, str):
            options = {"all": options}
        if not isinstance(options, dict):
            raise DubError(f"glossary entry {term!r} must be a translation map or a string")
        valid = {}
        for lang, value in options.items():
            if lang not in {*VOICES, "all"} or not isinstance(value, str) or not value.strip():
                raise DubError("glossary language or term value is invalid")
            valid[lang] = value.strip()
        clean[term] = valid
    return clean


@contextmanager
def local_work(out):
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".working-", dir=out) as name:
        yield Path(name)


def assemble_language(source, duration_ms, information, background, language, items, output):
    folder = output / language
    folder.mkdir(parents=True, exist_ok=True)
    captions, traced, audio_slots = [], [], []
    for record, pcm in items:
        traced.append(record)
        if pcm is None:
            continue
        audio_slots.append((record["dub_start_ms"], record["source_end_ms"], pcm))
        start = srt_timestamp(record["dub_start_ms"])
        end = srt_timestamp(max(record["dub_start_ms"] + 70, record["dub_end_ms"]))
        text = " ".join(record["translation"].split())
        captions.append(f"{len(captions) + 1}\n{start} --> {end}\n{text}\n")
    put_json(folder / f"segments.{language}.json", traced)
    subtitle = folder / f"subtitles.{language}.srt"
    put_bytes(subtitle, "\n".join(captions).encode())
    eligible = [row for row in traced if row["source_text"] or row.get("reason") != "no recognized speech"]
    skipped = sum(row["status"] != "dubbed" for row in eligible)
    result = {
        "status": "ok" if not skipped else "partial", "dubbed_segments": len(audio_slots),
        "skipped_speech_segments": skipped, "expected_speech_segments": len(eligible),
        "review_segments": sum(row.get("quality", {}).get("severity") == "review" for row in traced),
        "median_cer": _median([row["quality"]["cer"] for row in traced if "quality" in row]),
        "background": "original outside replaced slots; stereo side information within them",
        "segments": f"{language}/segments.{language}.json", "subtitles": f"{language}/subtitles.{language}.srt",
    }
    if not audio_slots and eligible:
        result["status"] = "failed"
        return result
    with local_work(folder) as work:
        mixed, integrated = mix_track(background, audio_slots, duration_ms, information["channels"])
        audio = work / "mix.wav"
        audio.write_bytes(wave_bytes(mixed, MIX_RATE))
        final = folder / f"video.{language}.mp4"
        method, outcome_duration = mux(source, information, audio, subtitle, language, final, duration_ms)
    length_delta = round(abs(information["duration_s"] - outcome_duration) * 1000, 3)
    result.update(video=f"{language}/video.{language}.mp4", video_codec_method=method,
                  integrated_speech_lufs=integrated, speech_loudness_on_target=integrated is not None and abs(integrated + 16) <= 1,
                  duration_error_ms=length_delta, duration_on_target=length_delta <= 100,
                  max_sync_offset_ms=max((abs(row.get("sync_offset_ms", 0)) for row in traced), default=0))
    return result


def _median(values):
    if not values:
        return None
    sorted_values = sorted(values)
    mid = len(values) // 2
    return round((sorted_values[mid] + sorted_values[(len(values) - 1) // 2]) / 2, 4)


def run(args, transport=None):
    start = monotonic()
    output = args.out.resolve()
    report = {"schema_version": 1, "status": "failed", "ai_dubbed": True, "languages": {}}
    languages = list(dict.fromkeys(code.strip().lower() for code in args.langs.split(",") if code.strip()))
    cache = None if args.no_cache else output / ".cache" / "v1"
    output.mkdir(parents=True, exist_ok=True)
    with Providers(args.jobs, cache, args.max_cost_inr, transport) as provider:
        try:
            source = args.input.resolve()
            if source.suffix.lower() not in ALLOWED or not source.is_file():
                raise DubError("input must be a local MP4, MOV, MKV or WebM file")
            if not languages or any(language not in VOICES for language in languages):
                raise DubError("unsupported --langs; use " + ", ".join(VOICES))
            if args.max_cost_inr is not None and (not math.isfinite(args.max_cost_inr) or args.max_cost_inr < 0):
                raise DubError("--max-cost-inr must be finite and nonnegative")
            info = probe(source)
            duration_ms = round(info["duration_s"] * 1000)
            if duration_ms > 900_100 or (duration_ms < 59_900 and not args.allow_short_input):
                raise DubError("expected a source video of 1–15 minutes; --allow-short-input is for smoke tests")
            report.update(source={"name": source.name, **info}, llm_model=provider.llm_model or None)
            glossary = glossary_settings(args.glossary)
            voices = voice_settings(args.voices, languages)
            speech = decode_track(source, info["audio_index"], ASR_RATE, 1).reshape(-1)[:sample_index(duration_ms, ASR_RATE)]
            background = decode_track(source, info["audio_index"], MIX_RATE, 2)
            active, levels = frame_activity(speech)
            spans = speech_spans(active, levels, duration_ms)
            log("speech_regions", segments=len(spans), duration_ms=duration_ms)
            rows = []
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                tasks = [pool.submit(transcribe_window, provider, speech, span, i, cut_wave)
                         for i, span in enumerate(spans, 1)]
                rows = [task.result() for task in tasks]
            put_json(output / "transcript.en.json", {
                "language": "en", "timing_method": "energy-filtered WebRTC VAD window boundaries",
                "input_duration_ms": duration_ms, "segments": rows,
            })
            report["source_windows"] = len(rows)
            report["source_recognition_errors"] = sum(row["status"] == "error" for row in rows)
            report["source_provider"] = provider.summary()
            automatic, planning = plan_glossary(provider, rows)
            report["planning"] = planning
            script = "codemix" if args.code_mixed else "native"
            terms = {}
            for lang in languages:
                terms[lang] = {**automatic, **{term: options.get(lang) or options.get("all") or term
                                              for term, options in glossary.items()}}
            rendered = {lang: {} for lang in languages}
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                pending = {}
                for i, row in enumerate(rows):
                    next_start = rows[i + 1]["start_ms"] if i + 1 < len(rows) else duration_ms
                    slot_end = min(row["end_ms"] + 550, max(row["end_ms"], next_start - 30))
                    for lang in languages:
                        pending[pool.submit(render_segment, provider, row, lang, voices[lang], slot_end,
                                            script, terms[lang])] = (lang, i)
                for future in as_completed(pending):
                    lang, i = pending[future]
                    try:
                        rendered[lang][i] = future.result()
                    except Exception as exc:
                        row = rows[i]
                        rendered[lang][i] = ({"id": row["id"], "source_text": row["text"],
                                              "source_start_ms": row["start_ms"], "source_end_ms": row["end_ms"],
                                              "status": "skipped", "reason": safe_error(exc)}, None)
                    record = rendered[lang][i][0]
                    log("segment", language=lang, segment=record["id"], status=record["status"],
                        reason=record.get("reason"), attempts=len(record.get("attempts", [])))
            for lang in languages:
                items = [rendered[lang][i] for i in range(len(rows))]
                try:
                    metrics = assemble_language(source, duration_ms, info, background, lang, items, output)
                except Exception as exc:
                    metrics = {"status": "failed", "reason": safe_error(exc)}
                metrics["voice"] = voices[lang]
                metrics["provider"] = provider.summary([e for e in provider.events if e.get("language") == lang])
                report["languages"][lang] = metrics
            report["status"] = "ok" if not report["source_recognition_errors"] and all(
                metrics["status"] == "ok" for metrics in report["languages"].values()
            ) else "partial"
        except Exception as exc:
            report["error"] = safe_error(exc)
        finally:
            elapsed = round(monotonic() - start, 3)
            report.update(elapsed_s=elapsed, provider=provider.summary(), requests=provider.events,
                          cost_note="Estimated using Bodhan published rates. LLM spend and failed calls are excluded.")
            duration = report.get("source", {}).get("duration_s")
            if duration:
                report["cost_inr_per_source_minute"] = round(report["provider"]["cost_inr"] * 60 / duration, 5)
                report["runtime_target_applicable"] = 280 <= duration <= 340 and len(languages) == 3
                report["runtime_under_30min"] = elapsed <= 1800
            for language in languages:
                report["languages"].setdefault(language, {"status": "failed", "reason": report.get("error", "not run")})
            put_json(output / "report.json", report)
            log("run_complete", status=report["status"], seconds=elapsed, report=str(output / "report.json"))
    return 0 if report["status"] == "ok" else 1


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--langs", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--voices", type=Path)
    parser.add_argument("--code-mixed", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--max-cost-inr", type=float)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--allow-short-input", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 12:
        parser.error("--jobs must be between 1 and 12")
    return args


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(Path.cwd() / ".env", override=False)
    return run(parse(argv))


if __name__ == "__main__":
    raise SystemExit(main())
