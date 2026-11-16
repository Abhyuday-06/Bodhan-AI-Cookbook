"""Derive grounded listening scripts while preserving the language boundary."""
from __future__ import annotations

from html.parser import HTMLParser
import html
import re
import unicodedata

from .chapter import HEADS
from .core import StageError, context, public_error
from .translate import MATH, NUMBER, check_script, translate_block, translate_markdown

LIST_ITEM = re.compile(r"(?m)^\s*(?:[-*+]\s+|(\d+)[.)]\s+)")
LETTER = re.compile(r"(?<!\w)[A-Z]{1,5}(?!\w)")
MATH_WORDS = {
    r"\angle": "angle", r"\triangle": "triangle", r"\parallel": "is parallel to",
    r"\perp": "is perpendicular to", r"\neq": "is not equal to", r"\ne": "is not equal to",
    r"\approx": "is approximately", r"\equiv": "is equivalent to", r"\leq": "is at most",
    r"\geq": "is at least", r"\le": "is at most", r"\ge": "is at least",
    r"\pm": "plus or minus", r"\times": "times", r"\cdot": "times", r"\div": "divided by",
    r"\pi": "pi", r"\theta": "theta", r"\alpha": "alpha", r"\beta": "beta", r"\gamma": "gamma",
    r"\infty": "infinity", r"\circ": "degrees", r"\rightarrow": "leads to",
    "∠": "angle", "∥": "is parallel to", "⊥": "is perpendicular to", "°": "degrees",
    "=": "equals", "≈": "is approximately", "<": "is less than", ">": "is greater than",
    "+": "plus", "-": "minus", "−": "minus", "×": "times", "*": "times", "/": "divided by",
}
OPERATORS = re.compile("|".join(re.escape(k) + (r"(?![A-Za-z])" if k.startswith("\\") else "")
                                for k in sorted(MATH_WORDS, key=len, reverse=True)))


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None


def table_cells(text):
    if text.lower().lstrip().startswith("<table"):
        parser = TableParser()
        parser.feed(text)
        return parser.rows
    return [[v.replace(r"\|", "|").strip() for v in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
            for line in text.splitlines() if "|" in line and not re.fullmatch(r"[\s|:\-]+", line)]


def simple_math(value):
    math = MATH.sub(lambda m: m.group().strip("$").removeprefix(r"\[").removesuffix(r"\]")
                    .removeprefix(r"\(").removesuffix(r"\)"), value)
    math = re.sub(r"\\(?:left|right|displaystyle|quad|qquad)\b", " ", math)
    math = re.sub(r"\\(?:mathrm|mathbf|mathit|text|operatorname)\{([^{}]*)\}", r"\1", math)
    math = re.sub(r"\\(?:overline|bar)\{([A-Z]{1,5})\}", r" line segment \1 ", math)
    math = re.sub(r"\\overrightarrow\{([A-Z]{1,5})\}", r" ray \1 ", math)
    math = re.sub(r"\\sqrt\{([^{}]+)\}", r" square root of (\1) ", math)
    math = re.sub(r"\\(?:d?frac|tfrac)\{([^{}]*)\}\{([^{}]*)\}", r" (\1) divided by (\2) ", math)
    math = re.sub(r"\^\{?2\}?(?!\d)", " squared ", math)
    math = re.sub(r"\^\{?3\}?(?!\d)", " cubed ", math)
    math = re.sub(r"\^\{?([^{}\s]+)\}?", r" to the power \1 ", math)
    math = re.sub(r"_\{?([^{}\s]+)\}?", r" subscript \1 ", math)
    math = re.sub(r"\\[,;:! ]", " ", math)
    math = OPERATORS.sub(lambda m: f" {MATH_WORDS[m.group()]} ", math)
    if re.search(r"[$\\{}_^]", math):
        return None
    return " ".join(math.split()).rstrip(".") + "."


def plain_md(text):
    text = re.sub(r"(?m)^\s*(?:#{1,6}|>)\s*", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = LIST_ITEM.sub(lambda m: (m[1] + ". ") if m[1] else "\n", text)
    text = re.sub(r"</?(?:strong|em|b|i|span|p|br)\b[^>]*>", " ", text, flags=re.I)
    return html.unescape(text).replace("**", "").replace("__", "").replace("\x60", "").strip()


def numbers(text):
    return {"".join(str(unicodedata.decimal(c)) if c.isdecimal() else c
                    for c in re.match(r"[-+−]?\d+(?:[.,:/–−-]\d+)*", m.group())[0]).replace("−", "-")
            for m in NUMBER.finditer(text)}


def english_table(text):
    rows = table_cells(text)
    if not rows:
        return None
    heading = rows[0]
    opening = "The table columns, in order, are " + "; ".join(heading) + "."
    for row in rows[1:]:
        if len(row) == len(heading):
            opening += " " + "; ".join(f"{key}: {value}" for key, value in zip(heading, row) if key or value) + "."
        else:
            opening += " Read the next row from left to right: " + "; ".join(row) + "."
    return opening


def paired_caption(blocks, index):
    left, right = max(0, index - 2), min(index + 3, len(blocks))
    adjacent = sorted((i for i in range(left, right) if blocks[i].kind == "caption"),
                      key=lambda i: (abs(i - index), i < index))
    for i in adjacent:
        lo, hi = sorted([i, index])
        if not any(b.kind in {"figure", "table", "heading"} for b in blocks[lo+1:hi]):
            caption, fig = blocks[i], blocks[index]
            if caption.page != fig.page:
                continue
            if caption.box and fig.box:
                overlap = min(caption.box[2], fig.box[2]) - max(caption.box[0], fig.box[0])
                if overlap <= 0:
                    continue
            return i
    return None


def judge_items(svc, items, ctx):
    if not items:
        return {}, None
    try:
        result = svc.judge(
            "Write for a student listening to a textbook. Return a JSON object readings indexed by input id. "
            "Each reading must be natural English only, with source labels and digit values unchanged. "
            "For equations read operations and grouped terms precisely, keeping every identifier and number. "
            "For tables explain headers and how the rows compare; include every numeric value when at most "
            "ten distinct values. For figures use only caption and directly related prose, describe only "
            "explicitly supported relationships. For an unsolved exercise do not supply its solution. "
            "Never transcribe images, invent measurements, write Indian-language text, or infer unseen detail. "
            "Omit readings you cannot support with the evidence.",
            items, ctx)
        readings = result.get("readings", {}) if result else {}
        return (readings if isinstance(readings, dict) else {}), None
    except Exception as exc:
        return {}, public_error(exc)


def acceptable(evidence, reading, kind):
    if not isinstance(reading, str) or not 8 <= len(reading) <= 1500:
        return False
    if not check_script(reading, "en") or re.search(r"[$\\|<>]", reading):
        return False
    expected, found = numbers(evidence), numbers(reading)
    if found - expected:
        return False
    if kind == "equation":
        if found != expected or set(LETTER.findall(evidence)) - set(LETTER.findall(reading)):
            return False
    if kind == "table" and len(expected) <= 10 and found != expected:
        return False
    return True


def script_section(svc, sources, translated, source, language, glossary, sec, mixed):
    by_ids = {item.ids: item for item in translated}
    ctx = context("narration_plan", language=language, section=sec)
    entries, diagnostics, metadata = [], [], []
    side = {}
    script_mode = "codemix" if mixed and language != "en" else "native"

    def english(b):
        if b.ids not in side:
            side[b.ids] = translate_block(svc, b, source, "en", glossary,
                                          {**ctx, "blocks": list(b.ids), "leg": f"{source}-en"}, []).text
        return side[b.ids]

    for i, b in enumerate(sources):
        if b.ids not in by_ids:
            continue
        if b.kind in {"table", "equation", "figure"}:
            id_ = b.ids[0]
            try:
                if b.kind == "figure":
                    cap_i = paired_caption(sources, i)
                    if cap_i is not None:
                        cap = sources[cap_i]
                        caption = english(cap)
                    else:
                        caption = ""
                    mentions = []
                    ref = re.search(r"\d+(?:\.\d+)+", caption)
                    if ref:
                        for near in sources[max(i-3, 0): i+4]:
                            if near.kind in {"text", "list"} and ref[0] in near.text:
                                mentions.append(english(near)[:420])
                    evidence = " ".join([caption, *mentions]).strip()
                    if evidence:
                        entries.append({"id": id_, "type": "figure", "evidence": evidence[:950]})
                    metadata.append((i, b, evidence, caption))
                else:
                    evidence = english(b)
                    fallback = english_table(evidence) if b.kind == "table" else simple_math(evidence)
                    summary = re.sub(r"<[^>]+>", " ", evidence).strip() if b.kind == "table" else evidence
                    if b.kind == "table" or fallback is None:
                        entries.append({"id": id_, "type": b.kind, "evidence": summary[:3000]})
                    metadata.append((i, b, summary, fallback))
            except StageError as exc:
                diagnostics.append({"blocks": list(b.ids), "policy": "english_evidence_unavailable", "reason": public_error(exc)})
    plan = {}
    # Cap each LLM prompt without clipping a complete section to a single request.
    for at in range(0, len(entries), 6):
        partial, error = judge_items(svc, entries[at:at+6], ctx)
        plan.update(partial)
        if error:
            diagnostics.append({"policy": "agent_fallback", "reason": error})
    prepared = {b.ids: (evidence, fallback, i) for i, b, evidence, fallback in metadata}

    def localize(text, b, apply_glossary=True):
        terms = ({e["en"].casefold(): e[language] for e in glossary if "en" in e and language in e}
                 if apply_glossary and script_mode == "native" else {})
        return translate_markdown(svc, text, "en", language, terms,
                                  {**ctx, "stage": "narration_translation", "blocks": list(b.ids)}, [], script_mode)

    def read_math(match, b):
        readable = simple_math(match.group())
        if readable is None:
            result, issue = judge_items(svc, [{"id": "math", "type": "equation", "evidence": match.group()}], ctx)
            if issue or not acceptable(match.group(), result.get("math"), "equation"):
                raise StageError("complex inline equation could not be verbalized safely")
            readable = result["math"]
        return localize(readable, b).rstrip(".") + " "

    result = []
    for i, b in enumerate(sources):
        found = by_ids.get(b.ids)
        if not found:
            continue
        ids, policy = list(b.ids), b.kind
        try:
            if b.kind == "code":
                diagnostics.append({"blocks": ids, "policy": "skipped", "reason": "code left in written lesson"})
                continue
            if b.kind in {"table", "equation", "figure"}:
                if b.ids not in prepared:
                    raise StageError("English evidence was unavailable")
                evidence, fallback, _ = prepared[b.ids]
                agent = plan.get(b.ids[0])
                draft = agent if acceptable(evidence, agent, b.kind) else fallback
                if b.kind == "figure":
                    cap_i = paired_caption(sources, i)
                    if cap_i is not None:
                        ids.extend(sources[cap_i].ids)
                    if not draft:
                        draft = "This figure has no verified spoken description. Refer to the diagram in the lesson."
                        diagnostics.append({"blocks": ids, "policy": "unverified_figure", "reason": "no caption or explicit description"})
                if not draft:
                    raise StageError(f"{b.kind} could not be verbalized safely")
                draft = MATH.sub(lambda m: simple_math(m.group()) or m.group(), draft)
                if MATH.search(draft):
                    raise StageError("narration plan still contains raw LaTeX")
                policy += "_agent" if draft == agent else "_fallback"
                text = localize(draft, b)
            else:
                raw = found.text
                if mixed and language != "en":
                    # Code mixing is a Bodhan translation mode, never LLM rewriting.
                    en = english(b)
                    raw = localize(en, b, apply_glossary=False)
                text = MATH.sub(lambda match: read_math(match, b), raw)
                text = plain_md(text)
                policy = "ordered_list" if b.kind == "list" else ("heading" if b.kind in HEADS else "read_prose")
            text = " ".join(text.split())
            if text:
                result.append({"text": text, "source_blocks": ids, "policy": policy})
        except StageError as exc:
            diagnostics.append({"blocks": ids, "policy": "skipped", "reason": public_error(exc)})
    narrated_with_figure = {id_ for item in result if item["policy"].startswith("figure_")
                            for id_ in item["source_blocks"][1:]}
    return [item for item in result if item["source_blocks"][0] not in narrated_with_figure], diagnostics
