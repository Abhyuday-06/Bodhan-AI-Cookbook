"""Bodhan-only translation: exact structural spans, pivot reuse and glossary."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha1
import re
import unicodedata

from .chapter import SOURCE_SCRIPTS, scripts
from .core import StageError, context, public_error

MATH = re.compile(r"(?s)(?<!\\)(?:\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|\$(?!\s|\$)(?:\\.|[^$\n])*?(?<!\\)\$)")
# Preserve Unicode digits and written symbols. Restrict units to a known set to avoid
# treating the following word as a unit.
NUMBER = re.compile(
    r"(?<![\d.])[+\-−]?\d+(?:[.,:/–−-]\d+)*(?:\s?(?:°[CF]?|%|‰|µm|μm|km|cm|mm|nm|m/s|kg|mg|mL|ml|kPa|Pa|Hz|kHz|MHz|"
    r"kWh|kW|km/h|L|g|m|s|h|mol|N|J|W|V|A|eV|Ω)(?![\w/])(?:[²³])?)?"
)
SYNTAX = re.compile(
    r"""(?mx) ^[ ]*(?:\#{1,6}[ ]+|>[ ]*|[-+*][ ]+|\d+[.)][ ]+|(?:[|:\- ]{3,})(?=\s*$))
    | <!--[\s\S]*?--> | </?[A-Za-z][^<>\n]*> | \x60+[^\x60]*\x60+
    | \]\([^\n)]*\) | (?:!\[|\[|\]) | \\[|*_~] | [*_|~]+ | [\n]+
    """
)
ESCAPE = re.compile(r"(?i)ZXQ[\s_-]*([0-9a-f]{6})[\s_-]*(\d{3,4})[\s_-]*QXZ")
SENTENCE = re.compile(r"(?<=[.!?।॥؟。])\s+")
MIXED_LABEL = re.compile(r"\b[A-Z]{1,5}\b")
META_TEXT = re.compile(r"(?i)^(?:here is (?:the )?translation|translated text|translation:|i cannot\b)")


def protect(text, terms=None):
    """Return ordered (offset, end, source, replacement) spans."""
    occupied = []
    patterns = [(MATH, None), (SYNTAX, None), (NUMBER, None)]
    if terms:
        patterns.append((re.compile(r"(?<!\w)(?:" + "|".join(
            re.escape(key) for key in sorted(terms, key=len, reverse=True)) + r")(?!\w)", re.I), terms))
    for pattern, glossary in patterns:
        for m in pattern.finditer(text):
            lo, hi = m.span()
            adjacent = text[lo - 1:lo] if lo else ""
            adjacent += text[hi:hi + 1]
            if glossary and any(unicodedata.category(c).startswith("M") for c in adjacent):
                continue
            if not any(lo < end and start < hi for start, end, *_ in occupied):
                original = m.group()
                occupied.append((lo, hi, original, glossary[original.casefold()] if glossary else original))
    return sorted(occupied)


def signature(text):
    return [(x[2]) for x in protect(text)]


def lexical(text):
    return sum(ch.isalpha() for ch in text)


def check_script(text, target, source="", mixed=False):
    counts = scripts(text)
    expected = SOURCE_SCRIPTS.get(target)
    total = sum(counts.values())
    borrowed = sum(len(x) for x in MIXED_LABEL.findall(text))
    if META_TEXT.search(text):
        return False
    if expected and total > 0 and expected != "LATIN":
        if counts[expected] == 0 and not (total <= 3 or total == borrowed and not lexical(source) > borrowed):
            return mixed and total <= 7
        if total >= 18 and counts[expected] / max(1, total - borrowed) < (0.15 if mixed else 0.38):
            return False
    if expected == "LATIN" and total >= 5 and counts["LATIN"] / total < 0.55:
        return False
    return True


def check_lexical(before, after, target, script):
    if not after.strip():
        return False
    letters = lexical(before)
    if letters >= 8 and lexical(after) < letters * 0.17:
        return False
    if letters >= 18 and lexical(after) > letters * 4.3:
        return False
    if letters >= 10 and after.strip().casefold() == before.strip().casefold() and not all(
        not c.isalpha() or c.isupper() for c in before
    ):
        return False
    return check_script(after, target, before, script == "codemix")


def split_text(text, limit):
    """Split at existing whitespace without dropping original separators."""
    if len(text) <= limit:
        return [text]
    pieces = []
    while len(text) > limit:
        window = text[:limit+1]
        cuts = list(re.finditer(r"(?<=[.!?।॥؟。])\s+", window))
        if not cuts or cuts[-1].start() < limit // 2:
            cuts = list(re.finditer(r"\s+", window))
        if not cuts or cuts[-1].start() < limit // 3:
            raise StageError("translation unit has no safe split point")
        cut = cuts[-1]
        pieces.extend((text[:cut.start()], cut.group()))
        text = text[cut.end():]
    if text:
        pieces.append(text)
    return pieces


def gloss_target(entries, target, key):
    return {row[key].casefold(): row[target] for row in entries if row.get(key) and row.get(target)}


def restore_tokens(text, spans, nonce, fragments):
    marks = list(ESCAPE.finditer(text))
    if len(marks) != len(spans) or any(m[1].lower() != nonce or int(m[2]) != i for i, m in enumerate(marks)):
        return None
    out = []
    start = 0
    for i, fragment in enumerate(fragments):
        end = marks[i].start() if i < len(marks) else len(text)
        result = text[start:end].strip()
        if not result and fragment.isspace():
            result = fragment
        elif result:
            result = fragment[:len(fragment) - len(fragment.lstrip())] + result + fragment[len(fragment.rstrip()):]
        out.append(result)
        if i < len(spans):
            out.append(spans[i][3])
            start = marks[i].end()
    return "".join(out)


def same_prose(bare, result):
    result = result.strip()
    return result if signature(bare) == signature(result) else None


def translate_markdown(svc, text, source, target, terms, ctx, trace, script="native"):
    if not text.strip() or source == target:
        return text
    spans = protect(text, terms)
    stripped = []
    tokenized = []
    cursor = 0
    nonce = sha1(text.encode("utf-8")).hexdigest()[:6]
    for i, (lo, hi, *_unused) in enumerate(spans):
        s = text[cursor:lo]
        stripped.append(s)
        tokenized.extend((s, f" ZXQ{nonce}{i:03d}QXZ "))
        cursor = hi
    stripped.append(text[cursor:])
    tokenized.append(text[cursor:])
    if not any(lexical(s) for s in stripped):
        return "".join(x + (spans[i][3] if i < len(spans) else "") for i, x in enumerate(stripped))

    protected = "".join(tokenized).strip()
    if len(protected) <= 2200 and len(spans) <= 65:
        try:
            result = svc.translate(protected, target, script, ctx)
            bare = ESCAPE.sub("", result)
            candidate = restore_tokens(result, spans, nonce, stripped)
            if candidate is not None and check_lexical("".join(stripped), bare, target, script):
                if signature(candidate) == signature(text):
                    trace.append({"method": "protected_context", "protected_spans": len(spans)})
                    return candidate
                # Glossary replacement can contain additional script characters but
                # may not introduce numbers, formatting or new delimiters.
        except StageError as exc:
            trace.append({"method": "protected_context_failed", "reason": public_error(exc)})

    def translate_piece(piece, retry=True):
        plain = piece.strip()
        if not lexical(plain):
            return piece
        leading = piece[:len(piece) - len(piece.lstrip())]
        trailing = piece[len(piece.rstrip()):]
        result = None
        try:
            result = same_prose(plain, svc.translate(plain, target, script, ctx))
        except StageError:
            if not retry:
                raise
        if result is not None and check_lexical(plain, result, target, script):
            return leading + result + trailing
        if retry and len(plain) > 55:
            chunks = split_text(plain, max(44, len(plain) // 2))
            if len(chunks) > 1:
                return leading + "".join(translate_piece(c, False) for c in chunks) + trailing
        # Source-only proper labels in short form (e.g. diagram label AB).
        if len(plain) <= 5 and MIXED_LABEL.fullmatch(plain):
            return piece
        raise StageError("a translation fragment failed language, coverage or structure checks")

    out = []
    for i, piece in enumerate(stripped):
        chunks = split_text(piece, 1100)
        out.extend(translate_piece(chunk) for chunk in chunks)
        if i < len(spans):
            out.append(spans[i][3])
    value = "".join(out)
    if signature(text) != signature(value):
        raise StageError("protected number, LaTeX or Markdown changed")
    trace.append({"method": "structural_fallback", "protected_spans": len(spans)})
    return value


def translate_block(svc, block, source, target, glossary, ctx, trace):
    if block.kind in {"code", "equation"} or not block.text or source == target:
        return replace(block)
    current = block.text
    if source != "en" and target != "en":
        current = translate_markdown(svc, current, source, "en", gloss_target(glossary, "en", source),
                                     {**ctx, "leg": f"{source}-en"}, trace)
        src = "en"
    else:
        src = source
    value = translate_markdown(svc, current, src, target, gloss_target(glossary, target, src),
                               {**ctx, "leg": f"{src}-{target}"}, trace)
    if signature(block.text) != signature(value):
        raise StageError("pivot changed protected structure")
    return replace(block, text=value)


def seed_glossary(svc, sections, source, targets, entries):
    if source != "en":
        return entries, {"mode": "supplied_only", "reason": "automatic terms curated only from English"}
    corpus = "\n".join(b.text for s in sections for b in s.blocks if b.kind in {"text", "heading"})
    # Sample across the chapter, not just the introduction.
    sample = "\n".join(corpus[i:i+1300] for i in range(0, len(corpus), max(1300, len(corpus)//5)))[:7000]
    try:
        result = svc.judge("Return terms: at most eight exact English phrases already present in the OCR text. "
                           "Choose repeated chapter-specific technical concepts (two to four words); no names, "
                           "numbers, paraphrases or translations.", {"ocr_text": sample}, context("glossary"))
    except Exception as exc:
        return entries, {"mode": "supplied_only", "reason": public_error(exc)}
    result = result.get("terms", []) if result else []
    if not isinstance(result, list):
        return entries, {"mode": "supplied_only", "reason": "invalid terms"}
    automatic = []
    used = {item.get("en", "").casefold() for item in entries}
    for term in result[:8]:
        if not isinstance(term, str) or not re.fullmatch(r"[A-Za-z]+(?:[ -][A-Za-z]+){1,3}", term):
            continue
        normalized = term.casefold()
        if normalized in used or len(re.findall(r"(?<!\w)" + re.escape(term) + r"(?!\w)", corpus, re.I)) < 3:
            continue
        used.add(normalized)
        row = {"en": term}
        for lang in targets:
            if lang == "en":
                continue
            try:
                value = svc.translate(term, lang, "native", context("glossary", language=lang)).strip()
                if not signature(value) and check_lexical(term, value, lang, "native"):
                    row[lang] = value
            except StageError:
                pass
        if len(row) > 1:
            automatic.append(row)
    return entries + automatic, {"mode": "supplied_and_model_suggested", "automatic_entries": len(automatic)}
