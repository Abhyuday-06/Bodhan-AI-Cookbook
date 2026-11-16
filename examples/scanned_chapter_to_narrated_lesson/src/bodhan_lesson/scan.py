"""Raster-only input, Indic-OCR, layout repair and recovery."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
import math
import re
import subprocess

from PIL import Image, ImageEnhance, ImageOps
from rapidfuzz.fuzz import ratio

from .core import Block, Page, StageError, atomic, context, json_file, log, public_error

HEADING_PREFIX = re.compile(r"^\s*#{1,6}\s+")
NOISE = {"header", "footer", "folio", "page-number", "pagenumber", "advertisement", "watermark"}
MATH = {"equation", "expression", "formula", "display-math"}
IMAGE = {"image", "picture", "figure", "chart", "diagram", "illustration"}
NOTE = {"handwritten", "handwriting", "handwritten-note", "margin-note", "marginalia"}
FOOTER = re.compile(r"(?i)(?:www\.|https?://|©|copyright|free downloads|all rights reserved|\breprint\b)")


def natural(name):
    return tuple(int(p) if i % 2 else p.casefold()
                 for i, p in enumerate(re.split(r"(\d+)", name)))


def discover(path: Path):
    if path.is_dir():
        items = sorted((p for p in path.iterdir() if p.is_file() and
                        p.suffix.lower() in (".png", ".jpg", ".jpeg")), key=lambda p: (natural(p.name), p.name))
        if not items:
            raise StageError("input folder contains no PNG or JPG pages")
        return [(p, None) for p in items]
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise StageError("--input must be a PNG/JPG folder or a scanned PDF")
    try:
        info = subprocess.run(["pdfinfo", str(path)], capture_output=True, check=True, timeout=30)
        count = re.search(rb"(?m)^Pages:\s+(\d+)", info.stdout)
        if count:
            return [(path, n) for n in range(1, int(count[1]) + 1)]
    except (OSError, subprocess.SubprocessError):
        pass
    raise StageError("pdfinfo could not read the PDF; install Poppler and check the input")


def render(path: Path, n: int | None, dpi: int):
    if n is None:
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
    else:
        try:
            data = subprocess.run(["pdftoppm", "-f", str(n), "-l", str(n), "-r", str(dpi),
                                   "-png", "-singlefile", str(path)],
                                  capture_output=True, check=True, timeout=75).stdout
            with Image.open(BytesIO(data)) as raw:
                image = raw.convert("RGB")
        except (OSError, subprocess.SubprocessError) as exc:
            raise StageError("Poppler could not rasterize page") from exc
    image.thumbnail((3300, 3300), Image.Resampling.LANCZOS)
    return image


def png(image):
    buf = BytesIO()
    image.save(buf, format="PNG", compress_level=3)
    return buf.getvalue()


def enhance(image, crop=False):
    out = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=0.5)
    if crop and max(out.size) < 1700:
        scale = min(2, 1900 / max(out.size))
        out = out.resize(tuple(round(n * scale) for n in out.size), Image.Resampling.LANCZOS)
    return ImageEnhance.Sharpness(out).enhance(1.3)


def kind_of(label, coarse, text):
    names = {str(value).lower().replace("_", "-").replace(" ", "-") for value in (label, coarse)}
    if names & NOISE:
        return "noise"
    if names & NOTE:
        return "note"
    if names & {"table-caption", "caption", "figure-caption", "image-caption"}:
        return "caption"
    if names & IMAGE:
        return "figure"
    if names & MATH:
        return "equation"
    if names & {"table"} or text.lower().lstrip().startswith("<table"):
        return "table"
    if names & {"title", "chapter-title", "titlepage-title"}:
        return "title"
    if names & {"section-title", "sectionheader", "section-header", "sub-section-title",
                "sub-sub-section-title", "chapter-end-section"}:
        return "subheading" if any("sub-" in name for name in names) else "heading"
    if names & {"list", "mcq"}:
        return "list"
    if names & {"infobox", "sidebar", "boxed-note"}:
        return "sidebar"
    if names & {"code"}:
        return "code"
    if HEADING_PREFIX.match(text):
        return "title" if text.startswith("# ") else "heading"
    if re.match(r"^\s*(?:[-*+] |[0-9]+[.)] )", text):
        return "list"
    if re.match(r"(?i)^\s*(?:fig(?:ure)?\.?|diagram)\s+[\d.]+", text):
        return "caption"
    if text.startswith(("$$", "\\[")):
        return "equation"
    if "|" in text and re.search(r"(?m)^\s*\|?\s*:?-{2,}", text):
        return "table"
    return "text"


def normalize(text, kind):
    text = text.strip()
    if kind in {"title", "heading", "subheading"} and not HEADING_PREFIX.match(text):
        return {"title": "# ", "heading": "## ", "subheading": "### "}[kind] + text
    if kind == "equation" and not text.startswith(("$", "\\[", "\\(")):
        return "$$\n" + text + "\n$$"
    return text


def flags_for(block):
    text = block.text
    flags = []
    if not text:
        return [] if block.kind in {"noise", "figure"} else ["empty"]
    if block.confidence is not None and block.confidence < 0.38:
        flags.append("low_layout_confidence")
    if "�" in text or re.search(r"(.)\1{7,}", text) and block.kind not in {"table", "equation", "code"}:
        flags.append("garbled")
    if len(text) >= 25 and sum(c.isalpha() for c in text) / len(text) < 0.25 and block.kind not in {
        "table", "equation", "code", "figure", "noise"
    }:
        flags.append("low_letter_density")
    return flags


def parse(response, number, size):
    try:
        md = response["choices"][0]["message"]["content"]
        if not isinstance(md, str):
            raise TypeError
    except (KeyError, IndexError, TypeError) as exc:
        raise StageError("OCR response missing Markdown") from exc
    raw = response.get("blocks") or []
    width, height = size
    blocks = []
    ordered = sorted(enumerate(raw), key=lambda p: (p[1].get("order", p[0])
                     if isinstance(p[1].get("order"), int) else p[0], p[0]))
    for ix, obj in ordered:
        value = str(obj.get("text") or "").strip()
        kind = kind_of(obj.get("label"), obj.get("type"), value)
        try:
            box = tuple(float(x) / (width if j % 2 == 0 else height)
                        for j, x in enumerate(obj.get("bbox_xyxy") or []))
            if len(box) != 4 or not all(math.isfinite(x) for x in box) or box[0] >= box[2] or box[1] >= box[3]:
                box = ()
        except (ValueError, TypeError):
            box = ()
        score = obj.get("conf")
        confid = float(score) if isinstance(score, (int, float)) and 0 <= score <= 1 else None
        b = Block((f"p{number:03d}b{ix+1:03d}",), number, kind,
                  normalize(value, kind) if value else "", box, confid)
        b.flags = flags_for(b)
        if obj.get("truncated") or obj.get("finish_reason") == "length":
            b.flags.append("truncated")
        blocks.append(b)
    fallback = not any(b.text and b.kind != "noise" for b in blocks)
    if fallback and md.strip():
        for ix, text in enumerate(re.split(r"\n\s*\n(?=\S)", md.strip()), 1):
            k = kind_of("", "", text)
            blocks.append(Block((f"p{number:03d}m{ix:03d}",), number, k, normalize(text, k)))
            blocks[-1].flags = flags_for(blocks[-1])
    return blocks, fallback


def column_order(blocks):
    """Only infer a gutter when multiple narrow text blocks support each lane."""
    lanes = [b for b in blocks if b.box and b.kind in {"text", "list", "sidebar"}
             and 0.18 < b.box[2] - b.box[0] < 0.63]
    candidates = []
    for gutter in (0.36, 0.42, 0.48, 0.5, 0.52, 0.58, 0.64):
        left = [b for b in lanes if b.box[2] <= gutter + 0.013]
        right = [b for b in lanes if b.box[0] >= gutter - 0.013]
        if not left or not right:
            continue
        overlap = min(max(b.box[3] for b in left), max(b.box[3] for b in right)) - max(
            min(b.box[1] for b in left), min(b.box[1] for b in right))
        threshold = 0.27 if len(left) + len(right) == 2 else 0.10
        if overlap > threshold and len(left) + len(right) >= len(lanes) * 0.7:
            candidates.append((len(left) + len(right), overlap, -abs(gutter - 0.5), gutter))
    if not candidates:
        return list(blocks), None
    gutter = max(candidates)[-1]

    def lane(b):
        x0, _, x1, _ = b.box
        return 0 if x1 <= gutter + 0.022 else 1 if x0 >= gutter - 0.022 else 2

    boxed = [b for b in blocks if b.box]
    barriers = sorted((b for b in boxed if lane(b) == 2), key=lambda b: b.box[1])
    remaining = [b for b in boxed if lane(b) != 2]
    out = []
    # A spanning block divides columns only if no lane block overlaps it materially.
    for b in barriers:
        split_y = (b.box[1] + b.box[3]) / 2
        band = [p for p in remaining if (p.box[1] + p.box[3]) / 2 < split_y]
        out.extend(sorted(band, key=lambda item: (lane(item), item.box[1])))
        out.append(b)
        done = {p.ids for p in band}
        remaining = [p for p in remaining if p.ids not in done]
    out.extend(sorted(remaining, key=lambda b: (lane(b), b.box[1])))
    return out + [b for b in blocks if not b.box], round(gutter, 2)


def padded_crop(image, box, pad=0.008):
    w, h = image.size
    x0, y0, x1, y1 = box
    return image.crop((max(0, int((x0-pad)*w)), max(0, int((y0-pad)*h)),
                       min(w, math.ceil((x1+pad)*w)), min(h, math.ceil((y1+pad)*h))))


def assess_layout(svc, blocks, page, gutter):
    # OCR text is evidence only: the model cannot return replacement text.
    if not (gutter or any(b.flags or b.kind in {"sidebar", "note"} or
                          b.box and (b.box[2] < .24 or b.box[0] > .76) for b in blocks)
            or any(a.box and b.box and a.box[1] > b.box[1] + 0.21
                   for a, b in zip(blocks, blocks[1:]))):
        return None
    return svc.judge(
        "Judge OCR layout, not wording. Return order (permutation of all given ids, keeping complete columns "
        "and attaching captions to their figures), doubtful (ids with clear OCR corruption, not "
        "technical vocabulary or another language), and annotations (ids clearly marginal handwritten notes). "
        "Never return OCR text, rewrites or invented words. Keep the provided order when uncertain.",
        [{"id": b.ids[0], "kind": b.kind, "box": b.box, "flags": b.flags,
          "ocr_excerpt": b.text[:240]} for b in blocks],
        context("layout", page=page))


def process_page(svc, number, spec, out, dpi, repair_limit):
    path, n = spec
    page = Page(number, f"{path.name}#{n}" if n else path.name)
    raw = {}
    evidence = {"original_order": [], "recoveries": [], "layout": "provider"}
    try:
        image = render(path, n, dpi)
        evidence["dimensions"] = list(image.size)
        raw["initial"] = svc.ocr(png(image), context("ocr", page=number))
        blocks, fallback = parse(raw["initial"], number, image.size)
        visible = [b for b in blocks if b.kind not in {"noise", "figure"}]
        if not visible or sum(bool(b.flags) for b in visible) >= max(3, len(visible) * 0.55):
            try:
                better = enhance(image)
                raw["enhanced_page"] = svc.ocr(png(better), context("ocr_enhanced", page=number))
                alt, alt_fallback = parse(raw["enhanced_page"], number, better.size)

                def score(items):
                    return sum(min(600, len(b.text)) * (0.25 if b.flags else 1)
                               for b in items if b.kind not in {"noise", "figure"})
                if score(alt) > score(blocks) * 1.05:
                    blocks, fallback = alt, alt_fallback
                    evidence["enhanced_selected"] = True
            except Exception as exc:
                evidence["enhanced_error"] = public_error(exc)
        evidence["markdown_fallback"] = fallback
        evidence["original_order"] = [b.ids[0] for b in blocks]
        content = [b for b in blocks if b.kind != "noise"]
        ordered, gutter = column_order(content)
        evidence["gutter"] = gutter
        if gutter is not None:
            evidence["layout"] = "columns"
        try:
            verdict = assess_layout(svc, ordered, number, gutter)
        except Exception as exc:
            verdict = None
            evidence["layout_judge_error"] = public_error(exc)
        by_id = {b.ids[0]: b for b in ordered}
        if isinstance(verdict, dict):
            proposed = verdict.get("order", [])
            if isinstance(proposed, list) and len(proposed) == len(by_id) and all(
                isinstance(p, str) and p in by_id for p in proposed
            ) and len(set(proposed)) == len(proposed):
                ordered = [by_id[p] for p in proposed]
                evidence["layout"] = "llm_validated_permutation"
            for field in ("annotations", "doubtful"):
                values = verdict.get(field)
                if not isinstance(values, list):
                    continue
                for id_ in values:
                    if isinstance(id_, str) and id_ in by_id and by_id[id_].kind not in {
                        "title", "heading", "subheading", "figure", "table", "equation", "caption"
                    }:
                        if field == "annotations":
                            b = by_id[id_]
                            if b.kind in {"note", "sidebar"} or (b.box and (b.box[2] < .24 or b.box[0] > .76)):
                                b.kind = "note"
                        elif "agent_doubt" not in by_id[id_].flags:
                            by_id[id_].flags.append("agent_doubt")
        for b in ordered:
            if b.kind == "figure" and b.box:
                asset = f"figures/{b.ids[0]}.png"
                try:
                    atomic(out / "source" / asset, png(padded_crop(image, b.box)))
                    b.asset = asset
                except (ValueError, OSError):
                    b.flags.append("figure_crop_failed")
        raw["crops"] = {}
        for b in [b for b in ordered if b.flags and b.box and b.kind not in {"figure", "note"}][:repair_limit]:
            id_ = b.ids[0]
            try:
                crop = enhance(padded_crop(image, b.box), crop=True)
                resp = svc.ocr(png(crop), context("ocr_crop", page=number, block=id_))
                raw["crops"][id_] = resp
                alt_blocks, _ = parse(resp, number, crop.size)
                pieces = [p.text for p in alt_blocks if p.text and p.kind not in {"noise", "figure"}]
                candidate = normalize("\n\n".join(pieces), b.kind) if pieces else ""
                repaired_flags = flags_for(replace(b, text=candidate, confidence=None))
                overlap = ratio(b.text, candidate) if b.text else None
                same_text = candidate and overlap is not None and overlap >= 92
                viable = (candidate and not repaired_flags and len(candidate) >= max(2, len(b.text) * 0.42)
                          and len(candidate) <= max(100, len(b.text) * 2.3))
                if viable and (not b.text or overlap >= 45) and (
                    not same_text or set(b.flags) <= {"low_layout_confidence"}
                ) and not any("truncated" in p.flags for p in alt_blocks):
                    b.text, b.flags = candidate, []
                    evidence["recoveries"].append({"block": id_, "status": "recovered", "agreement": overlap})
                else:
                    evidence["recoveries"].append({"block": id_, "status": "unresolved", "agreement": overlap})
            except Exception as exc:
                evidence["recoveries"].append({"block": id_, "status": "failed", "reason": public_error(exc)})
        page.blocks = ordered + [b for b in blocks if b.kind == "noise"]
        if not any(b.text and b.kind not in {"noise", "note"} for b in page.blocks):
            raise StageError("OCR returned no usable text")
    except Exception as exc:
        page.error = public_error(exc)
    evidence["checks"] = dict(Counter(f for b in page.blocks for f in b.flags))
    evidence["final_order"] = [b.ids[0] for b in page.blocks]
    evidence["block_types"] = dict(Counter(b.kind for b in page.blocks))
    page.info = evidence
    json_file(out / "source" / "pages" / f"{number:03d}.json",
              {"page": number, "input": page.name, "error": page.error, "checks": evidence,
               "blocks": [asdict(b) for b in page.blocks], "raw_ocr": raw})
    log("page_complete", page=number, status="failed" if page.error else "ok", checks=evidence["checks"])
    return page
