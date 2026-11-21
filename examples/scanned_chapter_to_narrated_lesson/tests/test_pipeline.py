"""Exercise rendering, HTTP contracts, recovery and real FFmpeg mastering."""
import base64
from collections import Counter
from io import BytesIO
import json
import math
import shutil
import struct
import wave

import httpx
from PIL import Image
import pytest

from bodhan_lesson.__main__ import parse_args
from bodhan_lesson.audio import brief_section_script, cer, join_short_prose, speech_chunks, verified_clip
from bodhan_lesson.chapter import assemble, merge_tables
from bodhan_lesson.core import Block, KEYS, Page, ProviderCreditExhausted, Services
from bodhan_lesson.pipeline import execute
from bodhan_lesson.scan import column_order, discover, render
from bodhan_lesson.translate import ESCAPE, signature, translate_markdown


class NoJudge:
    def judge(self, *_):
        return None


def test_brief_narration_keeps_an_intact_statement_and_its_source():
    items = [
        {"text": "Section heading", "source_blocks": ["b1"], "policy": "heading"},
        {"text": "A straight angle measures 180 degrees. It can be split into two angles.",
         "source_blocks": ["b2"], "policy": "read_prose"},
    ]
    assert brief_section_script(items) == [
        {"text": "A straight angle measures 180 degrees.", "source_blocks": ["b2"], "policy": "read_prose"},
    ]
    assert items[1]["text"].endswith("two angles.")


def test_short_prose_groups_keep_block_provenance_and_structural_boundaries():
    items = [
        {"text": "One sentence.", "source_blocks": ["b1"], "policy": "read_prose"},
        {"text": "Another sentence.", "source_blocks": ["b2"], "policy": "read_prose"},
        {"text": "New section", "source_blocks": ["b3"], "policy": "heading"},
        {"text": "Third sentence.", "source_blocks": ["b4"], "policy": "read_prose"},
    ]
    groups = join_short_prose(items, limit=40)
    assert groups[0]["text"] == "One sentence. Another sentence."
    assert groups[0]["source_blocks"] == ["b1", "b2"]
    assert groups[1:] == items[2:]


def test_speech_budget_429_preserves_cached_audio_and_other_models(monkeypatch, tmp_path):
    monkeypatch.setenv(KEYS["speak"], "offline-test-only")
    monkeypatch.setenv(KEYS["translate"], "offline-test-only")
    calls = []

    def route(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/speech"):
            if len(calls) == 1:
                return httpx.Response(200, content=b"RIFFsample")
            return httpx.Response(429, json={"error": {"type": "budget_exceeded"}})
        return httpx.Response(200, json={"translation": "परीक्षण"})

    with Services(tmp_path, 1, transport=httpx.MockTransport(route)) as service:
        assert service.speak("पहला", "hi", "Kavya", {}) == b"RIFFsample"
        for _ in range(2):
            with pytest.raises(ProviderCreditExhausted, match="credit exhausted"):
                service.speak("दूसरा", "hi", "Kavya", {})
        attempts = []
        with pytest.raises(ProviderCreditExhausted):
            verified_clip(service, "दूसरा", "hi", "Kavya", None, {}, attempts)
        assert len(attempts) == 1
        assert service.speak("पहला", "hi", "Kavya", {}) == b"RIFFsample"
        assert service.translate("test", "hi", "native", {}) == "परीक्षण"
    assert calls.count("/v1/audio/speech") == 2


def make_block(id_, text, page=1, kind="text", box=()):
    return Block((id_,), page, kind, text, box)


def test_column_order_with_spanning_heading():
    heading = make_block("H", "Topic", kind="heading", box=(.04, .05, .96, .09))
    left_1 = make_block("L1", "L1", box=(.05, .12, .45, .23))
    left_2 = make_block("L2", "L2", box=(.05, .25, .45, .42))
    right_1 = make_block("R1", "R1", box=(.55, .12, .95, .23))
    right_2 = make_block("R2", "R2", box=(.55, .25, .95, .43))
    order, gutter = column_order([heading, left_1, right_1, left_2, right_2])
    assert gutter and order == [heading, left_1, left_2, right_1, right_2]


def test_assemble_margins_cross_page_join_doubts_and_annotations(tmp_path):
    blocks = [
        make_block("p1h", "RUNNING HEADER", box=(.2, .02, .7, .09)),
        make_block("p1b", "Evaporation increases when a steady breeze", box=(.1, .73, .85, .92)),
        make_block("p1f", "99", box=(.4, .96, .6, .99)),
    ]
    dubious = make_block("p2d", "Suppo�ed text", 2)
    dubious.flags = ["garbled"]
    pages = [
        Page(1, "page-1.png", blocks),
        Page(2, "page-2.png", [
            make_block("p2h", "RUNNING HEADER", 2, box=(.2, .02, .7, .09)),
            make_block("p2b", "carries away water vapour.", 2, box=(.1, .12, .85, .18)),
            dubious,
            make_block("p2n", "Margin note", 2, "note"),
        ]),
    ]
    sections, lang, report = assemble(pages, tmp_path, NoJudge())
    assert lang == "en"
    assert sections[0].blocks[0].ids == ("p1b", "p2b")
    assert (tmp_path / "source/lesson.src.md").read_text(encoding="utf-8") == (
        "Evaporation increases when a steady breeze carries away water vapour.\n")
    assert report["quarantined"] == [["p2d"]]
    assert report["annotations"] == 1
    assert len(report["margin_removals"]) == 3


def test_split_html_tables_preserve_merged_cells():
    a = make_block("a", '<table><tr><th>Mass</th><th>Unit</th></tr><tr><td>5</td><td>kg</td></tr></table>')
    b = make_block("b", '<table><tr><th>Mass</th><th>Unit</th></tr><tr><td colspan="2">Unknown</td></tr></table>')
    merged = merge_tables(a, b, False)
    assert merged.count("<th>Mass</th>") == 1
    assert '<td colspan="2">Unknown</td>' in merged
    c = make_block("c", "<table><tr><th>Region</th><th>Unit</th></tr></table>")
    assert merge_tables(a, c, False) is None


def test_structure_identifies_mutations_and_falls_back_after_token_loss():
    text = "## Angles 6.2\n\n| Side | Value |\n| --- | --- |\n| Long edge | 12 cm |\n\n$$x=5$$"

    class DropsMarkers:
        def translate(self, value, *_):
            if ESCAPE.search(value):
                return "பிழையான மொழிபெயர்ப்பு"
            return "அளவு"

    trace = []
    result = translate_markdown(DropsMarkers(), text, "en", "ta", {}, {}, trace)
    assert trace[-1]["method"] == "structural_fallback"
    assert "12 cm" in result and "$$x=5$$" in result
    assert signature(result) == signature(text)
    for bad in ("11 cm", "12 mm", "12.0 cm"):
        assert signature(result.replace("12 cm", bad)) != signature(text)
    assert signature(result.replace("$$x=5$$", "$$x=6$$")) != signature(text)
    assert signature(result.replace("|", "", 1)) != signature(text)


def test_devanagari_glossary_does_not_match_prefix_of_longer_word():
    # A combining letter can extend an Indic word; inserting a partial glossary
    # term would silently drop the following character from the translation.
    term = "गणित"
    source = "गणितीय चर्चा"
    from bodhan_lesson.translate import protect
    assert not protect(source, {term: "math"})


def test_cer_normalizes_digits_and_retains_matra():
    assert cer("अभी १२।", "अभी 12")[0] == 0
    assert cer("क", "का") == (1, 1)
    chunks = speech_chunks("One short phrase. One more. Third phrase.")
    assert chunks == ["One short phrase. One more.", "Third phrase."]


def sine_wav(hz=231):
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        w.writeframes(b"".join(struct.pack("<h", int(5000 * math.sin(i * 2 * math.pi * hz / 24000)))
                              for i in range(24000)))
    return buf.getvalue()


@pytest.mark.skipif(not (shutil.which("pdfinfo") and shutil.which("pdftoppm")), reason="Poppler required")
def test_pdf_is_a_sequence_of_raster_pages(tmp_path):
    file = tmp_path / "scanned.pdf"
    page1 = Image.new("RGB", (80, 90), (210, 20, 20))
    page2 = Image.new("RGB", (80, 90), (20, 20, 210))
    Image.init()  # Register the JPEG encoder used internally by Pillow's PDF writer.
    page1.save(file, save_all=True, append_images=[page2])
    pages = discover(file)
    assert pages == [(file, 1), (file, 2)]
    first, second = [render(path, n, 150).getpixel((30, 40)) for path, n in pages]
    assert first[0] > first[2] and second[0] < second[2]


def block(i, label, text, y):
    return dict(order=i, label=label, type=label, text=text, conf=.96, bbox_xyxy=[40, y, 560, y+55])


def configure(monkeypatch):
    for name in KEYS.values():
        monkeypatch.setenv(name, "offline-test-placeholder")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "test-agent")
    monkeypatch.setenv("LLM_API_KEY", "offline-test-placeholder")


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg required")
def test_bodhan_wire_adapter_two_page_smoke_and_resume(tmp_path, monkeypatch):
    configure(monkeypatch)
    folder = tmp_path / "input"
    folder.mkdir()
    Image.new("RGB", (600, 800), (20, 40, 80)).save(folder / "page2.png")
    Image.new("RGB", (600, 800), (220, 40, 80)).save(folder / "page10.png")
    assert [p.name for p, _ in discover(folder)] == ["page2.png", "page10.png"]
    observed = Counter()
    transcripts = {}
    hi = "यह पाठ हमारी भाषा में है।"

    def route(req):
        payload = json.loads(req.content) if req.headers["content-type"].startswith("application/json") else None
        observed[(req.url.host, req.url.path)] += 1
        assert req.headers["Authorization"] == "Bearer offline-test-placeholder"
        if req.url.host == "example.test":
            assert payload["model"] == "test-agent"
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"terms":[]}'}}]})
        assert req.url.host == "api.bodhan.ai"
        if req.url.path == "/v1/chat/completions":
            assert payload["model"] == "indic-ocr"
            msg, = payload["messages"]
            image, = msg["content"]
            color = Image.open(BytesIO(base64.b64decode(image["image_url"]["url"].split(",")[1]))).getpixel((5, 5))
            if color[0] < 100:
                blocks = [block(0, "Chapter-title", "Water and Air", 45),
                          block(1, "Section-title", "Why water changes", 100),
                          block(2, "Paragraph", "Water changes as the temperature rises", 660),
                          block(3, "Footer", "Website for more downloads", 744)]
            else:
                blocks = [block(0, "Paragraph", "and as moving air passes over it.", 55),
                          block(1, "Section-title", "A measurement", 170),
                          block(2, "Paragraph", "The measured liquid rose by 4 cm.", 280),
                          block(3, "Equation", r"x+4=9", 400)]
            return httpx.Response(200, json={"choices": [{"message": {"content": "raw only"}}], "blocks": blocks})
        if req.url.path == "/translate":
            assert "source_language" not in payload and payload["target_language"] in {"hi", "ta"}
            if payload["target_language"] == "ta":
                return httpx.Response(403, json={"error": "dummy auth failure"})
            original = payload["text"]
            spans = [m.group() for m in ESCAPE.finditer(original)]
            text = (spans[0] + " " + hi + " " + " ".join(spans[1:])) if spans else hi
            return httpx.Response(200, json={"translation": text.strip(),
                                             "usage": {"completion_tokens": 12}, "truncated": False})
        if req.url.path == "/v1/audio/speech":
            assert payload["model"] == "indic-speak"
            assert json.loads(payload["instructions"])["lang"] == "hi"
            assert "ZXQ" not in payload["input"] and "Website" not in payload["input"]
            text = payload["input"]
            audio = sine_wav(231 + sum(ord(c) * (i + 1) for i, c in enumerate(text)) % 100000 / 500)
            transcripts[audio] = text
            return httpx.Response(200, content=audio)
        if req.url.path == "/v1/audio/transcriptions":
            assert b"indic-transcribe" in req.content and b'name="language"' in req.content
            position = req.content.index(b"RIFF")
            length = int.from_bytes(req.content[position+4:position+8], "little") + 8
            return httpx.Response(200, json={"text": transcripts[req.content[position:position+length]]})
        raise AssertionError(req.url)

    def run(langs):
        args = parse_args(["--input", str(folder), "--out", str(tmp_path / "out"),
                           "--langs", langs, "--jobs", "2"])
        return execute(args, httpx.MockTransport(route))

    assert run("hi,ta") == 1
    out = tmp_path / "out"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [p["status"] for p in report["pages"]] == ["ok", "ok"]
    assert report["status"] == "partial"
    assert report["languages"]["hi"]["status"] == "ok", report["languages"]["hi"]
    assert report["languages"]["ta"]["status"] != "ok"
    assert report["languages"]["hi"]["chapter_track"]["embedded_markers"] == 2
    assert report["languages"]["hi"]["sections"][0]["narration"]["lufs_on_target"]
    assert "rises and as moving" in (out / "source/lesson.src.md").read_text(encoding="utf-8")
    translated = (out / "hi/lesson.hi.md").read_text(encoding="utf-8")
    assert "4 cm" in translated and "x+4=9" in translated and "Website" not in translated
    assert (out / "hi/lesson.hi.mp3").stat().st_size > 2500
    calls_before = observed.copy()
    assert run("hi") == 0
    assert observed == calls_before
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["provider"]["cost_inr"] == 0 and report["provider"]["cache_hits"] > 5


def test_tts_repetition_rejected_and_regenerated():
    from bodhan_lesson.audio import verified_clip

    class Fake:
        def __init__(self):
            self.tags = []

        def speak(self, _text, _language, _voice, _ctx, _style, retry_tag):
            self.tags.append(retry_tag)
            return sine_wav()

        def transcribe(self, *_):
            return ("we can now " * 6) if len(self.tags) == 1 else "we can now measure the temperature"

    svc = Fake()
    attempts = []
    clips = verified_clip(svc, "we can now measure the temperature", "en", "Kavya", None, {}, attempts)
    assert svc.tags == ["", "qa-retry-2"]
    assert attempts[0]["repetition"]
    assert clips[0][1]["cer"] == 0
