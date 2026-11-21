"""Translate, fit and verify each source segment with a bounded recovery loop."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict
from hashlib import sha256

from rapidfuzz.distance import Levenshtein

from .media import MIX_RATE, decode_clip, fit_speed, stretch, trim_padding, wave_bytes
from .providers import DubError, safe_error

NUMBER = re.compile(r"(?<!\d)\d+(?:[.,:/–-]\d+)*")
ACRONYM = re.compile(r"(?<!\w)[A-Z][A-Z0-9]{1,9}(?!\w)")
FILLER = re.compile(r"(?i)\b(?:um|uh|erm)\b[, ]*")
PLACEHOLDER = re.compile(r"ZXQ([A-F0-9]{8})\s*(\d{2})QXZ", re.I)
SCRIPTS = {
    "hi": "DEVANAGARI", "mr": "DEVANAGARI", "bn": "BENGALI", "as": "BENGALI", "ta": "TAMIL",
    "te": "TELUGU", "gu": "GUJARATI", "kn": "KANNADA", "ml": "MALAYALAM", "or": "ORIYA",
    "pa": "GURMUKHI", "ur": "ARABIC",
}
SMALL_NUMBERS = {
    word: value for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
}
TENS = {
    word: value for value, word in enumerate(
        "twenty thirty forty fifty sixty seventy eighty ninety".split(), 2
    )
}
TENS = {word: value * 10 for word, value in TENS.items()}
ORDINALS = dict(zip(
    "first second third fourth fifth sixth seventh eighth ninth tenth".split(), range(1, 11), strict=True,
))
WORD_NUMBER = re.compile(
    r"(?i)\b(?:" + "|".join((*SMALL_NUMBERS, *TENS, *ORDINALS, "hundred", "thousand")) + r")\b"
)


def digits(value):
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in value)


def numbers(text):
    return Counter(digits(match[0]) for match in NUMBER.finditer(text))


def english_numerals(text):
    """Put common spoken quantities in a form the translation check can compare."""
    matches = list(WORD_NUMBER.finditer(text))
    result, end, i = [], 0, 0
    while i < len(matches):
        current = matches[i]
        word = current[0].lower()
        value = SMALL_NUMBERS.get(word, TENS.get(word))
        suffix = ""
        j = i + 1
        if word in ORDINALS:
            value = ORDINALS[word]
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(value, "th")
        if value is None:
            i += 1
            continue
        stop = current.end()
        # Handle six hundred, ninety-one, and conversational one eighty.
        while not suffix and j < len(matches):
            nxt = matches[j]
            gap = text[stop:nxt.start()]
            neighbor = nxt[0].lower()
            if re.fullmatch(r"[-\s]+", gap) and neighbor in {"hundred", "thousand"}:
                value *= 100 if neighbor == "hundred" else 1000
            elif re.fullmatch(r"\s+(?:and\s+)?", gap) and value >= 100 and value % 100 == 0 and (
                neighbor in SMALL_NUMBERS or neighbor in TENS
            ):
                value += SMALL_NUMBERS.get(neighbor, TENS.get(neighbor, 0))
            elif re.fullmatch(r"[-\s]+", gap) and value >= 20 and value % 10 == 0 and 1 <= SMALL_NUMBERS.get(neighbor, 0) <= 9:
                value += SMALL_NUMBERS[neighbor]
            elif gap.isspace() and 1 <= value <= 9 and neighbor in TENS:
                value = value * 100 + TENS[neighbor]
            else:
                break
            stop = nxt.end()
            j += 1
        result.extend((text[end:current.start()], f"{value}{suffix}"))
        end, i = stop, j
    return "".join(result) + text[end:]


def normalized(text):
    return "".join(digits(c) for c in unicodedata.normalize("NFKC", text).casefold()
                   if c.isalnum() or unicodedata.category(c).startswith("M"))


def phonetic_quality(expected, actual):
    ref, hyp = normalized(expected), normalized(actual)
    left, right = expected.casefold().split(), actual.casefold().split()
    before = Counter(zip(left, left[1:], left[2:], strict=False))
    after = Counter(zip(right, right[1:], right[2:], strict=False))
    repeats = any(n >= 3 and n >= before[key] + 2 for key, n in after.items())
    cer = Levenshtein.distance(ref, hyp) / max(1, len(ref))
    ratio = len(hyp) / max(1, len(ref))
    severe = not hyp or repeats or (len(ref) >= 10 and not .45 <= ratio <= 1.8)
    return {"cer": round(cer, 4), "repeat_detected": repeats, "length_ratio": round(ratio, 3),
            "severity": "reject" if severe or cer > .58 else "review" if cer > .26 else "pass"}


def contains(text, term):
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I) is not None


def target_script(text, language):
    if language == "en":
        return True
    letters = [ch for ch in text if ch.isalpha()]
    script = SCRIPTS[language]
    hits = sum(unicodedata.name(ch, "").startswith(script) for ch in letters)
    return hits >= max(1, len(letters) * .12)


def needed_terms(source, terms):
    selected = {term: rendered for term, rendered in terms.items() if contains(source, term)}
    for m in ACRONYM.finditer(source):
        if not any(contains(term, m[0]) for term in selected):
            selected.setdefault(m[0], m[0])
    return selected


def plan_glossary(svc, rows):
    """Extract exact source names and acronyms, never accept generated target text."""
    text = "\n".join(item["text"] for item in rows)
    if not text.strip():
        return {}, {"status": "skipped", "reason": "no source speech"}
    excerpt = text if len(text) <= 9000 else text[:5000] + "\n" + text[-4000:]
    try:
        planned = svc.judge(
            "Identify recurring proper names and technical acronyms in this English transcript. "
            "Return {\"preserve\": [\"exact source phrase\"]} with up to 15 phrases, each copied verbatim. "
            "Exclude generic vocabulary, common words, and sentence beginnings.",
            excerpt, {"phase": "glossary"},
        )
    except DubError as exc:
        return {}, {"status": "fallback", "reason": safe_error(exc)}
    items = planned.get("preserve", [])
    if not isinstance(items, list):
        items = []
    accepted = [item.strip() for item in items[:15] if isinstance(item, str) and
                re.fullmatch(r"[A-Za-z][A-Za-z0-9. -]{1,43}", item.strip()) and contains(text, item.strip())]
    return {item: item for item in accepted}, {"status": "ok", "preserved_terms": accepted}


def _plain_translation(svc, source, language, script, terms, ctx):
    result = svc.translate(source, language, script, ctx)
    if any(m and not contains(result, m) for m in terms.values()):
        return None
    if numbers(result) != numbers(source):
        return None
    return result


def translate_segment(svc, source, language, script, terms, ctx):
    if language == "en":
        return source
    selected = needed_terms(source, terms)
    plain = _plain_translation(svc, source, language, script, selected, ctx)
    if plain and (target_script(plain, language) or all(c.isupper() or not c.isalpha() for c in source)):
        return plain
    if not selected and not numbers(source):
        raise DubError("Indic-Translate returned an unexpected script")

    # Protect only the evidence that failed the first pass. The model sees the
    # surrounding sentence, so word order can still adapt to the target language.
    names = "|".join(re.escape(term) for term in sorted(selected, key=len, reverse=True))
    quantity = NUMBER.pattern + r"(?:st\b|nd\b|rd\b|th\b)?"
    wanted = re.compile((r"(?<!\w)(?:" + names + r")(?!\w)|" if names else "") + quantity, re.I)
    lookup = {term.casefold(): rendered for term, rendered in selected.items()}
    inserts = []
    nonce = sha256(source.encode()).hexdigest()[:8].upper()

    def hide(match):
        rendered = lookup.get(match[0].casefold(), match[0])
        inserts.append(rendered)
        return f" ZXQ{nonce}{len(inserts)-1:02}QXZ "

    masked = wanted.sub(hide, source)
    result = svc.translate(masked, language, script, {**ctx, "phase": "protected_translation"})
    seen = []

    def restore(match):
        number = int(match[2])
        if match[1].upper() != nonce or number >= len(inserts):
            raise DubError("Indic-Translate changed a protected marker")
        seen.append(number)
        return inserts[number]

    try:
        restored = PLACEHOLDER.sub(restore, result).strip()
    except DubError:
        restored = ""
    if (restored and sorted(seen) == list(range(len(inserts))) and numbers(restored) == numbers(source)
            and target_script(restored, language)):
        return restored

    # Older translation routes can echo masking tokens while dropping the surrounding text.
    # In that case, translate the prose spans and restore the verified original/curated values.
    words, end = [], 0
    for match in [*wanted.finditer(source), None]:
        prose = source[end:match.start() if match else len(source)]
        if any(char.isalpha() for char in prose):
            translated = _plain_translation(
                svc, prose.strip(), language, script, {}, {**ctx, "phase": "protected_span_fallback"},
            )
            if not translated or not target_script(translated, language):
                raise DubError("Indic-Translate could not verify the prose around a protected span")
            leading = prose[:len(prose) - len(prose.lstrip())]
            trailing = prose[len(prose.rstrip()):]
            prose = leading + translated.strip() + trailing
        words.append(prose)
        if match:
            words.append(lookup.get(match[0].casefold(), match[0]))
            end = match.end()
    result = "".join(words).strip()
    if numbers(result) != numbers(source) or not target_script(result, language):
        raise DubError("Indic-Translate failed script or numeral verification after recovery")
    return result


def compact_source(svc, source, terms, available_ratio, ctx):
    target = max(12, round(len(source) * max(.45, min(.91, available_ratio))))
    for_llm = {"english": source, "max_characters": target, "keep": list(terms)}
    try:
        result = svc.judge(
            "Return {\"english\": \"...\"}. Rephrase this line in shorter, natural English for a dub. "
            "Aim below max_characters. Remove filler and use compact syntax. Preserve every claim, number, "
            "proper name, acronym, negation and technical term. The line may continue in the next window. "
            "Leave an unfinished thought unfinished. Do not translate or add examples, conclusions or facts.",
            for_llm, {**ctx, "phase": "condense_english"},
        ).get("english")
    except DubError:
        result = None
    if isinstance(result, str):
        result = english_numerals(result).strip()
    if not isinstance(result, str) or not result.strip() or len(result) >= len(source):
        result = re.sub(r"\s+", " ", FILLER.sub("", source)).strip()
    if not result or len(result) >= len(source):
        return None
    stats = Counter(unicodedata.name(ch, "").split(" ")[0] for ch in result if ch.isalpha())
    if stats and stats["LATIN"] / sum(stats.values()) < .93:
        return None
    if numbers(result) != numbers(source) or any(not contains(result, term) for term in terms):
        return None
    return result


def render_segment(svc, row, language, voice, slot_end, script, terms):
    source = english_numerals(row["text"])
    slot = slot_end - row["start_ms"]
    ctx = {"language": language, "segment": row["id"]}
    trace = []
    fields = {"id": row["id"], "source_text": row["text"], "source_start_ms": row["start_ms"],
              "source_end_ms": row["end_ms"], "slot_end_ms": slot_end, "voice": voice, "attempts": trace}
    if row.get("status") != "speech":
        fields.update(status="skipped", reason=row.get("reason") or "no transcribed speech")
        return fields, None

    condensed = None
    original_translation = None
    best = None
    for attempt in range(3):
        text = condensed or source
        record = {"index": attempt + 1, "english": text}
        trace.append(record)
        try:
            if condensed or not original_translation:
                translation = translate_segment(svc, text, language, script, terms,
                                                {**ctx, "phase": "translation"})
                if condensed is None:
                    original_translation = translation
            else:
                translation = original_translation
            record["translation"] = translation
            fields["translation"] = original_translation or translation
            spoken = svc.speak(translation, language, voice, {**ctx, "phase": "synthesis"}, attempt)
            raw = trim_padding(decode_clip(spoken))
            duration = round(len(raw) * 1000 / MIX_RATE)
            record["natural_ms"] = duration
            speed = fit_speed(len(raw), slot)
            if speed is None:
                record.update(status="rejected", reason="duration exceeds 1.2x fit")
                keep = needed_terms(source, terms)
                ratio = .95 * slot * 1.2 / max(1, duration) * len(text) / len(source)
                proposal = compact_source(svc, source, keep, ratio, ctx)
                if proposal and (condensed is None or len(proposal) < len(condensed)):
                    condensed = proposal
                continue
            pcm = stretch(raw, speed, slot)
            actual = svc.transcribe(wave_bytes(pcm, MIX_RATE), len(pcm) / MIX_RATE, language,
                                    {**ctx, "phase": "back_transcription"})
            qa = phonetic_quality(translation, actual)
            record.update(status=qa["severity"], quality=qa, back_transcript=actual,
                          speed=round(speed, 5), rendered_ms=round(len(pcm) * 1000 / MIX_RATE))
            if qa["severity"] != "reject":
                candidate = (qa["cer"], pcm, translation, record, condensed)
                if best is None or candidate[0] < best[0]:
                    best = candidate
                if qa["severity"] == "pass":
                    break
        except DubError as exc:
            record.update(status="error", reason=safe_error(exc))
            if exc.status in {401, 402, 403} or "budget reached" in str(exc):
                break
    if best is None:
        last = trace[-1]
        fields.update(status="skipped", reason=last.get("reason", "speech verification rejected"))
        return fields, None
    _, pcm, translation, selected, chosen_english = best
    end = row["start_ms"] + selected["rendered_ms"]
    fields.update(status="dubbed", translation=translation, condensed_english=chosen_english,
                  dub_start_ms=row["start_ms"], dub_end_ms=end, sync_offset_ms=0,
                  speed=selected["speed"], quality=selected["quality"],
                  back_transcript=selected["back_transcript"])
    return fields, pcm


def transcribe_window(svc, samples, span, index, cutter):
    label = {"id": f"s{index:04d}", **asdict(span), "timing_source": "vad_window"}
    try:
        value = svc.transcribe(cutter(samples, span), span.seconds, "en",
                               {"segment": label["id"], "phase": "source_transcription"})
        # Silence/event markers are a non-speech outcome; they never enter the dub.
        cleaned = re.sub(r"\[(?:music|silence|applause|inaudible|noise)\]", "", value, flags=re.I).strip()
        if not any(c.isalnum() for c in cleaned):
            return {**label, "text": "", "status": "non_speech", "reason": "no recognized speech"}
        return {**label, "text": cleaned, "status": "speech"}
    except DubError as exc:
        return {**label, "text": "", "status": "error", "reason": safe_error(exc)}
