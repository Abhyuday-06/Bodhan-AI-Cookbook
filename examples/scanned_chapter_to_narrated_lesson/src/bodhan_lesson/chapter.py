"""Assemble clean source Markdown, sections and block lineage."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, replace
import math
import re
import unicodedata

from .core import Section, context, json_file, public_error, text_file
from .scan import FOOTER, HEADING_PREFIX

HEADS = {"title", "heading", "subheading"}
STRONG_END = re.compile(r"""[.!?।॥؟:;।。]['"’”»)\]]*$""")
TABLE_ROW = re.compile(r"<tr\b[^>]*>.*?</tr\s*>", re.I | re.S)
TABLE_CELL = re.compile(r"<(td|th)\b[^>]*>.*?</\1\s*>", re.I | re.S)
SOURCE_SCRIPTS = {
    "en": "LATIN", "hi": "DEVANAGARI", "mr": "DEVANAGARI", "ne": "DEVANAGARI",
    "sa": "DEVANAGARI", "doi": "DEVANAGARI", "mai": "DEVANAGARI", "kok": "DEVANAGARI",
    "ta": "TAMIL", "bn": "BENGALI", "as": "BENGALI", "te": "TELUGU", "kn": "KANNADA",
    "gu": "GUJARATI", "ml": "MALAYALAM", "or": "ORIYA", "pa": "GURMUKHI",
    "ur": "ARABIC", "ks": "ARABIC", "ks-Deva": "DEVANAGARI", "sd": "DEVANAGARI",
    "sd-Arab": "ARABIC", "brx": "DEVANAGARI", "mni": "MEETEI", "mni-Beng": "BENGALI",
    "sat": "OL",
}
FALLBACK_LANG = {"DEVANAGARI": "hi", "BENGALI": "bn", "ARABIC": "ur", **{
    script: lang for lang, script in SOURCE_SCRIPTS.items()
    if script not in {"DEVANAGARI", "BENGALI", "ARABIC"}}}


def scripts(text):
    return Counter(unicodedata.name(ch, "").split(" ", 1)[0] for ch in text if ch.isalpha())


def edge(b):
    if not b.box:
        return None
    if b.box[3] < 0.19:
        return "top"
    if b.box[1] > 0.81:
        return "bottom"
    return None


def norm_edge(text):
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", HEADING_PREFIX.sub("", text).casefold())).strip(" #.-")


def is_page_number(text):
    return re.fullmatch(r"(?:[^\S\n]*[-–—]?\s*)?\d{1,4}\s*[-–—]?", text.strip()) is not None


def drop_margins(pages):
    repetitions = defaultdict(set)
    for p in pages:
        for b in p.blocks:
            if edge(b) and b.text and len(b.text) < 140 and b.kind not in {"table", "equation", "caption", "note"}:
                repetitions[edge(b), norm_edge(b.text)].add(p.number)
    common = {k for k, v in repetitions.items() if k[1] and len(v) >= max(2, math.ceil(len(pages) * 0.24))}
    drops = []
    kept = []
    for p in pages:
        if p.error:
            continue
        for b in p.blocks:
            margin = edge(b)
            normalized = norm_edge(b.text)
            reason = None
            if b.kind == "noise":
                reason = "ocr_margin_label"
            elif b.kind == "note":
                continue
            elif margin and b.kind in {"text", "title", "heading", "subheading"}:
                if margin == "bottom" and len(b.text) < 190 and FOOTER.search(b.text):
                    reason = "footer_pattern"
                elif (margin, normalized) in common:
                    reason = "repeated_margin"
                elif is_page_number(b.text):
                    reason = "page_number"
            elif not b.box and b.kind == "text" and len(b.text) < 135 and FOOTER.search(b.text):
                if b is p.blocks[-1]:
                    reason = "unboxed_final_footer"
            if reason:
                drops.append({"blocks": list(b.ids), "reason": reason})
            else:
                kept.append(deepcopy(b))
    return kept, drops


def table_rows(text):
    if text.lower().lstrip().startswith("<table"):
        return TABLE_ROW.findall(text)
    return [line.strip() for line in text.splitlines() if "|" in line]


def row_key(row):
    return re.sub(r"\s+", "", row).casefold()


def table_width(row):
    if row.lower().startswith("<tr"):
        return len(TABLE_CELL.findall(row))
    return len(re.split(r"(?<!\\)\|", row.strip("|")))


def merge_tables(a, b, at_edge):
    ar, br = table_rows(a.text), table_rows(b.text)
    if not ar or not br or table_width(ar[0]) != table_width(br[0]):
        return None
    ah, bh = "<th" in ar[0].lower(), "<th" in br[0].lower()
    html_a, html_b = ar[0].lower().startswith("<tr"), br[0].lower().startswith("<tr")
    if html_a != html_b:
        return None
    repeated = row_key(ar[0]) == row_key(br[0])
    if not repeated and not (at_edge and html_a and ah and not bh):
        return None
    latter = br[1:] if repeated else br
    if not html_a and repeated and latter and re.fullmatch(r"[\s|\-:]+", latter[0]):
        latter = latter[1:]
    if html_a:
        # Keep original tags and nesting; leave irregular/multi-body HTML separate.
        a_end = re.search(r"(?is)(</tbody\s*>\s*)?</table\s*>$", a.text)
        if a_end is None or re.search(r"(?i)<tfoot|</thead>\s*</table>", a.text):
            return None
        if not latter:
            return None
        return a.text[:a_end.start()] + "\n" + "\n".join(latter) + "\n" + a_end.group()
    return "\n".join(ar + latter) if latter else None


def sentence_join(a, b):
    left, right = a.text.rstrip(), b.text.lstrip()
    if not left or not right or STRONG_END.search(left) or right[0].isdigit():
        return None
    if a.kind != "text" or b.kind != "text" or len(left) < 35:
        return None
    if b.box and b.box[1] > .42 or a.box and a.box[3] < .52:
        return None
    if right[0].islower() or (
        not right[0].isupper() and right[0].isalpha() and
        ((a.box and a.box[3] > .70 and b.box and b.box[1] < .27) or left.endswith(("­", "-")))
    ):
        return left[:-1] + right if left.endswith("­") else left + " " + right
    return None


def body_text(blocks, asset_prefix=""):
    out = []
    for b in blocks:
        if b.asset:
            out.append(f"![]({asset_prefix}{b.asset})")
        if b.text:
            out.append(b.text)
    return "\n\n".join(out).strip() + "\n"


def assemble(pages, out, svc, hint=None):
    kept, drops = drop_margins(pages)
    notes = [b for p in pages for b in p.blocks if b.kind == "note" and b.text]
    uncertain = [b for b in kept if b.flags]
    if notes:
        json_file(out / "source" / "annotations.json", [asdict(b) for b in notes])
    if uncertain:
        json_file(out / "source" / "doubtful.json", [asdict(b) for b in uncertain])
    # A doubtful heading still marks a section boundary in the diagnostics, but its
    # unverified words do not enter translation or narration.
    clean, joins = [], []
    previous = None
    for b in kept:
        if (b.flags and b.kind != "figure") or not (b.text or b.asset):
            previous = None
            continue
        merged = None
        if previous and b.page == previous.page + 1:
            a = clean[-1]
            if a.kind == b.kind == "table":
                merged = merge_tables(a, b, bool(previous.box and previous.box[3] > .72 and b.box and b.box[1] < .25))
            else:
                merged = sentence_join(previous, b)
                if merged and a is not previous:
                    joiner = "" if previous.text.endswith("­") else " "
                    merged = a.text.rstrip().removesuffix("­") + joiner + b.text.lstrip()
            if merged:
                clean[-1] = replace(a, text=merged, ids=a.ids + b.ids)
                joins.append({"blocks": list(clean[-1].ids), "kind": a.kind})
        if not merged:
            clean.append(b)
        previous = b
    lang, detection = detect_source(clean, svc, hint)
    sections = sectionize(clean)
    text_file(out / "source" / "lesson.src.md", body_text(clean))
    line = 1
    provenance = []
    for sec in sections:
        for b in sec.blocks:
            count = len(body_text([b]).splitlines())
            provenance.append({"section": sec.index, "kind": b.kind, "source_blocks": list(b.ids),
                               "line_start": line, "line_end": line + count - 1, "figure": b.asset})
            line += count + 1
    json_file(out / "source" / "provenance.json", provenance)
    return sections, lang, {"language_detection": detection, "margin_removals": drops, "joins": joins,
                             "annotations": len(notes), "quarantined": [list(b.ids) for b in uncertain if b.kind != "figure"],
                             "source_counts": dict(Counter(b.kind for b in clean)),
                             "structure_capture": "OCR inventory only; ground truth unavailable"}


def detect_source(blocks, svc, hint):
    if hint:
        return hint, {"method": "argument", "language": hint}
    sample = "\n".join(HEADING_PREFIX.sub("", b.text) for b in blocks if b.kind in {"text", "title", "heading"}
                       and b.text)[:7000]
    counts = scripts(sample)
    script = counts.most_common(1)[0][0] if counts else "LATIN"
    candidate = FALLBACK_LANG.get(script, "en")
    options = [code for code, value in SOURCE_SCRIPTS.items() if value == script]
    evidence = {"method": "unicode_script", "script_counts": dict(counts), "language": candidate}
    if len(options) > 1 or script not in FALLBACK_LANG:
        try:
            result = svc.judge("Identify the dominant source language of the supplied OCR text. "
                               "Choose a code from options. Return language only; do not rewrite the text.",
                               {"options": options or list(SOURCE_SCRIPTS), "ocr_text": sample[:2400]},
                               context("source_detection"))
            if result and result.get("language") in (options or list(SOURCE_SCRIPTS)):
                candidate = result["language"]
                evidence.update(method="script_and_llm", language=candidate)
        except Exception as exc:
            evidence["judge_error"] = public_error(exc)
    return candidate, evidence


def sectionize(blocks):
    sections = []
    group = []
    seen_words = 0
    for b in blocks:
        is_head = b.kind in {"title", "heading"} or (b.kind == "subheading" and seen_words >= 170)
        if group and ((is_head and seen_words > 0) or (seen_words >= 750 and b.kind in {"text", "list"})):
            sections.append(group)
            group, seen_words = [], 0
        group.append(b)
        if b.kind not in HEADS:
            seen_words += len(b.text.split())
    if group:
        sections.append(group)
    return [Section(i, next((HEADING_PREFIX.sub("", b.text) for b in group if b.kind in HEADS),
                            f"Part {i}"), group) for i, group in enumerate(sections, 1)]
