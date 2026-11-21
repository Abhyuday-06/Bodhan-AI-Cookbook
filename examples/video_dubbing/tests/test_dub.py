"""Verify the timestamp logic and one real FFmpeg round trip."""
import json
import shutil

import httpx
import numpy as np
import pytest
from bodhan_dub import __main__ as cli
from bodhan_dub.media import MIX_RATE, ffmpeg, fit_speed, mix_track, probe, speech_spans, wave_bytes
from bodhan_dub.providers import KEY_NAMES, DubError, Providers
from bodhan_dub.workflow import english_numerals, numbers, phonetic_quality, translate_segment


def test_vad_keeps_a_pause_and_caps_long_windows():
    active = np.zeros(1100, dtype=bool)
    active[8:370] = True
    active[440:625] = True
    spans = speech_spans(active, np.where(active, -15., -70.), 33000)
    assert len(spans) == 3
    assert spans[0].start_ms == 195
    assert all(span.seconds < 10.7 for span in spans)
    assert spans[1].end_ms < spans[2].start_ms
    assert speech_spans(np.zeros(5, dtype=bool), np.zeros(5), 150) == []


def test_timing_limit_and_quality():
    assert fit_speed(24000, 1200) == 1
    assert 1.18 < fit_speed(24000, 850) <= 1.2
    assert fit_speed(24000, 790) is None
    assert phonetic_quality("यह १२ है।", "यह 12 है")["cer"] == 0
    assert phonetic_quality("one phrase now", ("one phrase now " * 5))["repeat_detected"]


def test_spoken_english_numbers_can_be_compared_with_indic_digits():
    source = "Period one, chapter six. An angle is ninety or one eighty degrees."
    translated_numerals = "१ ६ ९० १८०"
    assert numbers(english_numerals(source)) == numbers(translated_numerals)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires FFmpeg loudness filters")
def test_mastering_fits_loudness_target_without_spilling_into_silence():
    ticks = np.arange(MIX_RATE * 5)
    speech = (1400 * np.sin(ticks / MIX_RATE * 390 * 2 * np.pi)).astype(np.int16)
    speech[::MIX_RATE] = 26000
    bed = np.zeros((MIX_RATE * 6, 2), dtype=np.int16)
    audio, measured = mix_track(bed, [(350, 5350, speech)], 6000, 2)
    assert -17 <= measured <= -15
    assert not audio[:round(.35 * MIX_RATE)].any()
    assert not audio[round(5.35 * MIX_RATE):].any()
    assert len(audio) == len(bed)


def test_prose_recovered_when_translation_omits_protected_context():
    class MasksOnlyProvider:
        def translate(self, text, language, script, context):
            assert language == "hi"
            if context.get("phase") == "protected_translation":
                return text.split()[0]
            return "अभ्यास"

    assert translate_segment(MasksOnlyProvider(), "1st exercise", "hi", "native", {}, {}) == "1st अभ्यास"


def test_provider_budget_429_closes_only_the_exhausted_model(monkeypatch):
    monkeypatch.setenv(KEY_NAMES["speak"], "offline-test-only")
    monkeypatch.setenv(KEY_NAMES["translate"], "offline-test-only")
    calls = []

    def route(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/speech"):
            return httpx.Response(429, json={"error": {"type": "budget_exceeded"}})
        return httpx.Response(200, json={"translation": "परीक्षण"})

    with Providers(1, None, transport=httpx.MockTransport(route)) as provider:
        for _ in range(2):
            with pytest.raises(DubError, match="credit exhausted") as exhausted:
                provider.speak("परीक्षण", "hi", "Kavya", {}, 0)
            assert exhausted.value.status == 402
        assert provider.translate("test", "hi", "native", {}) == "परीक्षण"
    assert calls.count("/v1/audio/speech") == 1


def test_30_second_smoke_language_failure_and_resume(monkeypatch, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for media smoke test")

    for key in KEY_NAMES.values():
        monkeypatch.setenv(key, "offline-test-only")
    monkeypatch.setenv("LLM_API_KEY", "offline-test-only")
    monkeypatch.setenv("LLM_MODEL", "demo-planner")
    monkeypatch.setenv("LLM_BASE_URL", "https://planner.example.test/v1")
    source = tmp_path / "clip.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=navy:s=160x120:r=12:d=30",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=30:sample_rate=24000",
           "-c:v", "libx264", "-c:a", "aac", "-t", 30, source)

    # Force two known utterance windows for the mocked ASR; VAD is unit tested above.
    activity = np.zeros(1000, dtype=bool)
    activity[40:91] = True
    activity[200:252] = True
    monkeypatch.setattr(cli, "frame_activity", lambda _: (activity, np.where(activity, -20., -70.)))
    voiced = (3900 * np.sin(np.arange(MIX_RATE) / MIX_RATE * 360 * 2 * np.pi)).astype(np.int16)
    checks = []
    spoken = "पानी साफ है।"

    def route(request):
        if request.url.host == "planner.example.test":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"preserve":[]}'}}]})
        checks.append(request.url.path)
        if request.url.path == "/translate":
            return httpx.Response(404)
        if request.url.path == "/v1/chat/completions":
            payload = json.loads(request.content)
            assert payload["model"] == "indic-translate"
            if payload["target_language_code"] == "ta":
                return httpx.Response(403)
            return httpx.Response(200, json={"choices": [{"message": {"content": spoken},
                                                          "finish_reason": "stop"}]})
        if request.url.path == "/v1/audio/speech":
            assert json.loads(request.content)["response_format"] == "wav"
            return httpx.Response(200, content=wave_bytes(voiced, MIX_RATE), headers={"Content-Type": "audio/mpeg"})
        if request.url.path == "/v1/audio/transcriptions":
            assert b"indic-transcribe" in request.content
            hindi = b"\r\n\r\nhi\r\n" in request.content
            return httpx.Response(200, json={"text": spoken if hindi else "The water is clear."})
        raise AssertionError(request.url.path)

    out = tmp_path / "out"
    args = cli.parse(["--input", str(source), "--langs", "hi,ta", "--out", str(out), "--allow-short-input"])
    assert cli.run(args, httpx.MockTransport(route)) == 1
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["languages"]["hi"]["dubbed_segments"] == 2
    assert report["languages"]["ta"]["status"] == "failed"
    assert report["languages"]["hi"]["max_sync_offset_ms"] == 0
    assert report["languages"]["hi"]["speech_loudness_on_target"]
    assert abs(probe(out / "hi/video.hi.mp4")["duration_s"] - 30) <= .1
    assert "00:00:01,155" in (out / "hi/subtitles.hi.srt").read_text(encoding="utf-8")
    assert (out / "transcript.en.json").is_file()
    args.langs = "hi"
    checks.clear()
    assert cli.run(args, httpx.MockTransport(route)) == 0
    assert set(checks) <= {"/translate"}
