"""Tests for digital audio analysis (clipping, silence, duration)."""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from bodhan_eval.checks.audio_analysis import AudioAnalysisCheck
from bodhan_eval.types import DatasetItem, ErrorCategory


def _generate_synthetic_wav(
    duration_sec: float = 1.0,
    framerate: int = 24000,
    amplitude: int = 15000,
    silence_start: float | None = None,
    silence_duration: float = 0.0,
    clipped: bool = False,
) -> bytes:
    """Generate a synthetic 16-bit mono PCM WAV for testing."""
    total_frames = int(duration_sec * framerate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)

        samples = []
        for i in range(total_frames):
            t = i / float(framerate)
            if silence_start is not None and silence_start <= t < (silence_start + silence_duration):
                samples.append(0)
            elif clipped:
                samples.append(32767 if (i % 2 == 0) else -32768)
            else:
                # 440 Hz sine wave
                s = int(amplitude * math.sin(2 * math.pi * 440 * t))
                samples.append(s)

        raw = struct.pack(f"<{len(samples)}h", *samples)
        wf.writeframes(raw)

    return buf.getvalue()


@pytest.mark.asyncio
async def test_audio_check_clean():
    check = AudioAnalysisCheck()
    wav_bytes = _generate_synthetic_wav(duration_sec=2.0, amplitude=10000)
    item = DatasetItem(
        id="aud-1",
        source="Short sentence.",
        lang="hi",
        audio=wav_bytes,
    )
    flags = await check.run(item, "छोटा वाक्य।", "hi")
    assert len(flags) == 0


@pytest.mark.asyncio
async def test_audio_check_silence():
    check = AudioAnalysisCheck()
    # 5-second audio with 2.5-second internal silence
    wav_bytes = _generate_synthetic_wav(
        duration_sec=5.0,
        silence_start=1.0,
        silence_duration=2.5,
    )
    item = DatasetItem(
        id="aud-2",
        source="Sentence with long pause.",
        lang="hi",
        audio=wav_bytes,
    )
    flags = await check.run(item, "लंबे विराम वाला वाक्य।", "hi")
    assert len(flags) >= 1
    assert any(f.error_type == ErrorCategory.SPEECH_GARBLED for f in flags)
    assert any("silence" in f.evidence for f in flags)


@pytest.mark.asyncio
async def test_audio_check_clipping():
    check = AudioAnalysisCheck()
    # Audio with 100% clipped samples
    wav_bytes = _generate_synthetic_wav(duration_sec=1.5, clipped=True)
    item = DatasetItem(
        id="aud-3",
        source="Clipped audio sentence.",
        lang="hi",
        audio=wav_bytes,
    )
    flags = await check.run(item, "विकृत ऑडियो वाक्य।", "hi")
    assert len(flags) >= 1
    assert any(f.error_type == ErrorCategory.SPEECH_GARBLED for f in flags)
    assert any("clipping" in f.evidence for f in flags)
