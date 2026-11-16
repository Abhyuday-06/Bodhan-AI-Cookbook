"""Orchestrate pages and languages with independent failure boundaries."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import math
import shutil

import yaml

from .audio import chapter_track, slug, synth_section
from .chapter import HEADS, SOURCE_SCRIPTS, assemble, body_text
from .core import (ALL_VOICES, VOICE_PAIRS, Block, Page, Services, StageError,
                   context, json_file, log, public_error, text_file)
from .narrate import script_section
from .scan import HEADING_PREFIX, discover, process_page
from .translate import seed_glossary, signature, translate_block

STYLES = {"AIR style news", "Customer Care", "TV style news", "advertisements", "anger",
          "children's stories", "disgust", "educational lecture", "fear", "happy", "news", "sad",
          "single person narration audiobook", "surprise"}


def yaml_read(path, field):
    if path is None:
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise StageError(f"could not read {field} YAML") from exc


def config_for(args, langs, source):
    raw = yaml_read(args.glossary, "glossary")
    if not isinstance(raw, dict):
        raise StageError("glossary must map terms to language codes")
    entries = []
    for term, val in raw.items():
        if not isinstance(term, str) or not term.strip() or signature(term) or not isinstance(val, dict):
            raise StageError("glossary terms must be plain, nonempty text with a language mapping")
        entry = {source: term.strip()}
        for lang, word in val.items():
            if (lang not in SOURCE_SCRIPTS or not isinstance(word, str) or not word.strip()
                    or "\n" in word or signature(word) or "ZXQ" in word.upper()):
                raise StageError("glossary values must be plain, nonempty text in supported languages")
            entry[lang] = word.strip()
        entries.append(entry)
    raw = yaml_read(args.voices, "voices")
    if not isinstance(raw, dict):
        raise StageError("voices must map languages to a voice or {voice, style}")
    voices = {}
    for key, val in raw.items():
        if key not in VOICE_PAIRS:
            raise StageError("voices contains an unsupported language")
        val = {"voice": val} if isinstance(val, str) else val
        if not isinstance(val, dict) or not isinstance(val.get("voice"), str) or val["voice"] not in ALL_VOICES:
            raise StageError(f"invalid Indic-Speak voice for {key}")
        style = val.get("style")
        if style is not None and (not isinstance(style, str) or style not in STYLES):
            raise StageError(f"invalid Indic-Speak style for {key}")
        voices[key] = (val["voice"], style)
    return entries, {lang: voices.get(lang, (VOICE_PAIRS[lang][0], None)) for lang in langs}


def error_section(section, exc):
    return {"section": section.index, "source_title": section.title, "status": "failed", "error": public_error(exc),
            "markdown": "", "wav": None, "script": [], "translation": [], "narration": {"status": "failed"}}


def run_section(svc, section, src, lang, glossary, voice, style, mixed, dest, work):
    started = monotonic()
    log("section_start", language=lang, section=section.index)
    translated, written, checks = [], [], []
    for block in section.blocks:
        ctx = context("translation", section=section.index, language=lang, blocks=list(block.ids))
        trace = []
        check = {"source_blocks": list(block.ids), "kind": block.kind, "protected_spans": len(signature(block.text))}
        try:
            value = translate_block(svc, block, src, lang, glossary, ctx, trace)
            verified = signature(value.text) == signature(block.text)
            if not verified:
                raise StageError("structure signature changed")
            translated.append(value)
            written.append(value)
            check.update(status="ok", invariant_match=True, methods=trace)
        except StageError as exc:
            check.update(status="failed", invariant_match=False, reason=public_error(exc), methods=trace)
            written.append(Block(block.ids, block.page, block.kind,
                                 "<!-- Translation unavailable: " + ", ".join(block.ids) + " -->",
                                 asset=block.asset))
        checks.append(check)
    items, diagnostics = script_section(svc, section.blocks, translated, src, lang, glossary, section.index, mixed)
    title = next((HEADING_PREFIX.sub("", b.text) for b in translated if b.text and b.kind in HEADS),
                 f"{section.index:02d}")
    file = dest / "narration" / f"{section.index:02d}-{slug(title, section.index)}.{lang}.mp3"
    wav = work / f"{section.index:03d}.wav"
    try:
        audio = synth_section(svc, items, lang, voice, style, section.index, file, wav)
    except StageError as exc:
        audio = {"status": "failed", "error": public_error(exc), "file": None, "duration_s": None, "cer": None}
    covered_ids = {id_ for item in items for id_ in item["source_blocks"]}
    missing = [{"blocks": list(b.ids), "reason": "translation_or_script_unavailable"} for b in section.blocks
               if not set(b.ids) <= covered_ids and b.kind != "code" and (b.text or b.asset)]
    manifest = []
    line = 1
    for b in written:
        span = len(body_text([b], "../source/").splitlines())
        if b.text or b.asset:
            manifest.append({"source_blocks": list(b.ids), "kind": b.kind, "line_start": line, "line_end": line + span - 1})
            line += span + 1
    status = "ok" if audio["status"] == "ok" and all(c["status"] == "ok" for c in checks) and not missing else "partial"
    if not audio.get("file") and not translated:
        status = "failed"
    report = {"section": section.index, "source_title": section.title, "title": title,
              "status": status, "translation": checks, "script": items, "narration": audio,
              "planning_decisions": diagnostics, "coverage_missing": missing,
              "duration_s": audio.get("duration_s"), "cer": audio.get("cer"),
              "elapsed_s": round(monotonic() - started, 3), "lineage": manifest}
    log("section_complete", language=lang, section=section.index, status=status, cer=report["cer"])
    return {**report, "markdown": body_text(written, "../source/").strip(), "wav": wav if audio.get("file") else None}


def run_language(svc, sections, src, lang, glossary, voice, style, mixed, out, jobs):
    started = monotonic()
    dest = out / lang
    dest.mkdir(parents=True, exist_ok=True)
    chapter = None
    error = None
    with TemporaryDirectory(dir=dest) as tmp:
        work = Path(tmp)
        result = {}
        with ThreadPoolExecutor(max_workers=min(jobs, 4)) as pool:
            tasks = {pool.submit(run_section, svc, section, src, lang, glossary, voice, style,
                                 mixed, dest, work): section for section in sections}
            for task in as_completed(tasks):
                section = tasks[task]
                try:
                    result[section.index] = task.result()
                except Exception as exc:
                    result[section.index] = error_section(section, exc)
        done = [result[s.index] for s in sections]
        chunks, line = [], 1
        for r in done:
            md = r.pop("markdown")
            if md:
                chunks.append(md)
                for span in r.get("lineage", []):
                    span["line_start"] += line - 1
                    span["line_end"] += line - 1
                line += len(md.splitlines()) + 1
        track_files = [(r["wav"], r.get("title") or r["source_title"], r["section"]) for r in done if r.get("wav")]
        for r in done:
            r.pop("wav", None)
        text_file(dest / f"lesson.{lang}.md", "\n\n".join(chunks) + "\n")
        json_file(dest / f"narration_script.{lang}.json",
                  {"ai_generated": True, "language": lang, "voice": voice, "style": style, "sections": done})
        try:
            chapter = chapter_track(track_files, lang, dest, work)
        except StageError as exc:
            error = public_error(exc)
    complete = bool(done) and all(r["status"] == "ok" for r in done) and chapter is not None
    return {"status": "ok" if complete else "partial" if track_files else "failed",
            "ai_generated": True, "error": error, "voice": voice, "style": style,
            "translated_sections": sum(bool(r["translation"]) and all(t["status"] == "ok" for t in r["translation"]) for r in done),
            "narrated_sections": len(track_files), "expected_sections": len(sections), "chapter_track": chapter,
            "sections": [{**{k: v for k, v in r.items() if k not in {"script", "narration"}},
                          "narration": {k: v for k, v in r["narration"].items() if k not in {"accepted_chunks", "attempts"}},
                          "narration_attempts": len(r["narration"].get("attempts", [])),
                          "narration_retries": sum(a["attempt"] > 1 or a["split_depth"] > 0
                                                   for a in r["narration"].get("attempts", [])),
                          "narration_qa": {"review_chunks": sum(a.get("qa") == "review"
                                                              for a in r["narration"].get("accepted_chunks", []))}}
                         for r in done],
            "elapsed_s": round(monotonic() - started, 3)}


def execute(args, transport=None):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = monotonic()
    report = {"schema_version": 1, "ai_generated_narration": True, "status": "failed",
              "pages": [], "languages": {}, "quality_targets": {}}
    langs = list(dict.fromkeys(x.strip().lower() for x in args.langs.split(",") if x.strip()))
    with Services(None if args.no_cache else out / ".cache" / "v1", args.jobs, args.max_inr, transport) as svc:
        try:
            if not langs or any(x not in VOICE_PAIRS for x in langs):
                raise StageError("unknown or empty --langs; supported: " + ", ".join(VOICE_PAIRS))
            if args.source_lang and args.source_lang not in SOURCE_SCRIPTS:
                raise StageError("unknown --source-lang")
            if args.max_inr is not None and (not math.isfinite(args.max_inr) or args.max_inr < 0):
                raise StageError("--max-inr must be finite and nonnegative")
            if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
                raise StageError("ffmpeg and ffprobe must be on PATH")
            specs = discover(args.input)
            if not 1 <= len(specs) <= 30:
                raise StageError("expected no more than 30 pages for one chapter")
            report["input"] = {"pages": len(specs), "format": "image_folder" if args.input.is_dir() else "pdf_raster",
                               "path": args.input.name, "dpi": args.dpi}
            if len(specs) < 5:
                report["input"]["warning"] = "fewer than five pages, useful for smoke runs"
            if not svc.keys["ocr"]:
                raise StageError("missing BODHAN_OCR_KEY")
            report["configuration"] = {"api_concurrency": args.jobs, "code_mixed": args.code_mixed,
                                       "llm_model": svc.llm_model or None, "ocr_crop_limit": args.ocr_repair_limit}
            by_page = {}
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                pending = {pool.submit(process_page, svc, i, spec, out, args.dpi, args.ocr_repair_limit): i
                           for i, spec in enumerate(specs, 1)}
                for task in as_completed(pending):
                    i = pending[task]
                    try:
                        by_page[i] = task.result()
                    except Exception as exc:
                        by_page[i] = Page(i, specs[i-1][0].name, error=public_error(exc))
            pages = [by_page[i] for i in sorted(by_page)]
            report["pages"] = [{"page": p.number, "input": p.name, "status": "failed" if p.error else "ok",
                                "error": p.error, **p.info, "provider": svc.stats([e for e in svc.events
                                                                                 if e.get("page") == p.number])}
                               for p in pages]
            sections, src, assembly = assemble(pages, out, svc, args.source_lang)
            report.update(source_language=src, assembly=assembly)
            if not sections:
                raise StageError("no usable chapter sections after OCR cleanup")
            entries, voices = config_for(args, langs, src)
            glossary, glossary_qa = seed_glossary(svc, sections, src, langs, entries)
            json_file(out / "source" / "glossary.json", glossary)
            report["glossary"] = glossary_qa
            with ThreadPoolExecutor(max_workers=min(len(langs), args.jobs)) as pool:
                pending = {pool.submit(run_language, svc, sections, src, lang, glossary, *voices[lang],
                                       args.code_mixed, out, args.jobs): lang for lang in langs}
                for task in as_completed(pending):
                    lang = pending[task]
                    try:
                        report["languages"][lang] = task.result()
                    except Exception as exc:
                        report["languages"][lang] = {"status": "failed", "error": public_error(exc)}
            bad_pages = [p.number for p in pages if p.error]
            bad_langs = [lang for lang, data in report["languages"].items() if data["status"] != "ok"]
            report["status"] = "partial" if bad_pages or bad_langs else "ok"
            report["quality_targets"] = {
                "structure_capture": {"result": "unverified_without_reference", "failed_pages": bad_pages},
                "doubtful_ocr": {"quarantined_blocks": len(assembly["quarantined"]), "raw_artifacts": "source/pages/"},
                "structure_and_numbers": {"failed_languages": [lang for lang in bad_langs if
                    any(t["status"] != "ok" for s in report["languages"][lang].get("sections", []) for t in s["translation"])]},
                "narration_coverage": {"incomplete_languages": bad_langs},
                "content_fidelity": {"metric": "normalized character error rate", "scope": "accepted chunks; missing chunks counted separately"},
                "loudness": {"target_lufs": -16, "tolerance": 1, "sections_off_target": [
                    {"language": lang, "section": s["section"], "lufs": s["narration"]["lufs"]}
                    for lang, data in report["languages"].items() for s in data.get("sections", [])
                    if s["narration"].get("lufs_on_target") is False]},
            }
        except Exception as exc:
            report["error"] = public_error(exc)
        finally:
            for lang in langs:
                if lang not in report["languages"]:
                    report["languages"][lang] = {"status": "failed", "error": report.get("error", "not run")}
                language_events = [e for e in svc.events if e.get("language") == lang]
                report["languages"][lang]["provider"] = svc.stats(language_events)
                for section in report["languages"][lang].get("sections", []):
                    section["provider"] = svc.stats([e for e in language_events if e.get("section") == section["section"]])
            elapsed = round(monotonic() - started, 3)
            report["elapsed_s"] = elapsed
            report["quality_targets"]["runtime"] = {"elapsed_s": elapsed, "target_s": 1200,
                "benchmark_applicable": report.get("input", {}).get("pages") == 10 and len(langs) == 3,
                "cache_hits": svc.stats()["cache_hits"]}
            report["provider"] = svc.stats()
            report["cost_estimate_note"] = ("Bodhan posted INR rates; translation tokens estimated when usage is absent. "
                                            "Failed calls may be billable; LLM provider cost excluded. Cached requests cost zero.")
            report["calls"] = svc.events
            json_file(out / "report.json", report)
            log("run_complete", status=report["status"], elapsed_s=elapsed, report=str(out / "report.json"))
    return 0 if report["status"] == "ok" else 1
