"""Media timeline and sample-accurate voice placement."""
from __future__ import annotations

import json
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import webrtcvad

from .providers import DubError

ASR_RATE = 16000
MIX_RATE = 24000
FRAME_MS = 30
FRAME_SAMPLES = ASR_RATE * FRAME_MS // 1000


@dataclass(frozen=True)
class Span:
    start_ms: int
    end_ms: int

    @property
    def seconds(self):
        return (self.end_ms - self.start_ms) / 1000


def ffmpeg(*args, input_bytes=None):
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y", *map(str, args)],
            input=input_bytes, capture_output=True, check=True, timeout=210,
        )
    except FileNotFoundError as exc:
        raise DubError("FFmpeg must be installed and on PATH") from exc
    except subprocess.SubprocessError as exc:
        raise DubError("FFmpeg could not process this media") from exc
    return result.stdout


def probe(path: Path):
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-of", "json", "-show_streams", "-show_format", str(path)],
            capture_output=True, check=True, timeout=30,
        )
        value = json.loads(proc.stdout)
        streams = value.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"))
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        stream_duration = video.get("duration")
        duration = float(value["format"]["duration"] if stream_duration in (None, "N/A") else stream_duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return {"duration_s": duration, "audio_index": audio["index"] if audio else None,
                "video_index": video["index"], "video_codec": video.get("codec_name"),
                "channels": audio.get("channels", 0) if audio else 0}
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError, StopIteration) as exc:
        raise DubError("FFprobe could not find a video stream with a valid duration") from exc


def decode_track(path, audio_index, rate, channels):
    if audio_index is None:
        return np.empty((0, channels), dtype=np.int16)
    pcm = ffmpeg("-i", path, "-map", f"0:{audio_index}", "-af", "aresample=async=1:first_pts=0",
                 "-ac", channels, "-ar", rate, "-f", "s16le", "pipe:1")
    return np.frombuffer(pcm, dtype="<i2").reshape(-1, channels)


def wave_bytes(audio, rate=ASR_RATE):
    array = np.asarray(audio, dtype="<i2")
    channels = array.shape[1] if array.ndim == 2 else 1
    buf = BytesIO()
    with wave.open(buf, "wb") as output:
        output.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(array.tobytes())
    return buf.getvalue()


def decode_clip(data):
    pcm = ffmpeg("-i", "pipe:0", "-ac", 1, "-ar", MIX_RATE, "-f", "s16le", "pipe:1", input_bytes=data)
    samples = np.frombuffer(pcm, dtype="<i2")
    if not len(samples):
        raise DubError("Indic-Speak returned no audio samples")
    return samples


def _dbfs(frame):
    energy = np.mean(np.square(frame.astype(np.float32) / 32768))
    return float(10 * np.log10(max(1e-10, energy)))


def frame_activity(samples):
    vad = webrtcvad.Vad(2)
    count = len(samples) // FRAME_SAMPLES
    levels, voiced = [], []
    for i in range(count):
        frame = samples[i * FRAME_SAMPLES:(i + 1) * FRAME_SAMPLES]
        db = _dbfs(frame)
        levels.append(db)
        voiced.append(vad.is_speech(frame.astype("<i2", copy=False).tobytes(), ASR_RATE))
    if not count or max(levels) < -62:
        return np.zeros(count, dtype=bool), np.array(levels)
    # A low adaptive floor rejects noise while retaining quiet speech.
    floor = max(-62., min(-39., float(np.percentile(levels, 20)) + 6))
    return np.asarray(voiced) & (np.asarray(levels) >= floor), np.asarray(levels)


def speech_spans(active, levels, length_ms, *, pause_ms=390, max_ms=10500):
    """Group voiced runs and cut long continuous runs near a low-energy edge."""
    if not len(active):
        return []
    # VAD may fire for a single click. Requiring three detected frames in a
    # five-frame neighborhood still retains short words.
    hits = np.flatnonzero(np.asarray(active) & (np.convolve(active, np.ones(5), mode="full")[2:len(active) + 2] >= 3))
    groups = []
    for hit in hits:
        if groups and (hit - groups[-1][-1]) * FRAME_MS <= pause_ms:
            groups[-1].append(hit)
        else:
            groups.append([hit])
    spans = []
    for group in groups:
        if len(group) < 3:
            continue
        start, end = group[0], group[-1] + 1
        while (end - start) * FRAME_MS > max_ms:
            next_cut = start + max_ms // FRAME_MS
            search_start = max(start + 1, next_cut - 60)
            cut = min(range(search_start, next_cut + 1),
                      key=lambda frame: (bool(active[frame]), levels[frame] + (next_cut - frame) * 0.1))
            spans.append(Span(int(start * FRAME_MS), int(cut * FRAME_MS)))
            start = cut
        spans.append(Span(int(start * FRAME_MS), int(end * FRAME_MS)))
    padded = []
    for i, span in enumerate(spans):
        previous_end = spans[i - 1].end_ms if i else 0
        next_start = spans[i + 1].start_ms if i + 1 < len(spans) else length_ms
        start = max((previous_end + span.start_ms) // 2 if i else 0, span.start_ms - 45)
        end = min((next_start + span.end_ms) // 2 if i + 1 < len(spans) else length_ms, span.end_ms + 60)
        if end - start >= 90:
            padded.append(Span(start, end))
    return padded


def sample_index(ms, rate):
    return round(ms * rate / 1000)


def cut_wave(samples, span):
    return wave_bytes(samples[sample_index(span.start_ms, ASR_RATE):sample_index(span.end_ms, ASR_RATE)])


def fit_speed(n_samples, slot_ms):
    if slot_ms <= 0 or n_samples <= 0:
        return None
    # Leave a small guard for AAC and atempo frame rounding.
    required = n_samples / max(1, sample_index(slot_ms - 12, MIX_RATE))
    return max(1., required) if required <= 1.2 else None


def stretch(samples, speed, slot_ms):
    max_samples = sample_index(slot_ms, MIX_RATE)
    if speed == 1:
        retimed = samples
    else:
        pcm = ffmpeg("-f", "s16le", "-ar", MIX_RATE, "-ac", 1, "-i", "pipe:0",
                     "-af", f"atempo={speed:.8f}", "-f", "s16le", "pipe:1",
                     input_bytes=np.asarray(samples, dtype="<i2").tobytes())
        retimed = np.frombuffer(pcm, dtype="<i2")
    if not len(retimed) or len(retimed) > max_samples:
        raise DubError("retimed speech does not fit without cutting samples")
    return retimed


def trim_padding(samples):
    # Remove only measurable exterior silence, with 25 ms guards.
    block = MIX_RATE // 100
    windows = [i for i in range(0, len(samples), block) if _dbfs(samples[i:i + block]) > -49]
    if not windows:
        raise DubError("Indic-Speak returned silence")
    guard = MIX_RATE // 40
    return samples[max(0, windows[0] - guard):min(len(samples), windows[-1] + block + guard)]


def loudness(samples, channels=1):
    source = np.asarray(samples, dtype="<i2").tobytes()
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-f", "s16le", "-ar", str(MIX_RATE), "-ac", str(channels),
         "-i", "pipe:0", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:dual_mono=true:print_format=json", "-f", "null", "-"],
        input=source, capture_output=True, timeout=60,
    )
    raw = proc.stderr.decode(errors="replace")
    match = re.search(r'\{\s*"input_i"[^{}]+\}', raw, re.S)
    if not match:
        return None
    value = float(json.loads(match[0])["input_i"])
    return value if math.isfinite(value) else None


def mix_track(original, placed, length_ms, channels):
    length = sample_index(length_ms, MIX_RATE)
    bed = np.zeros((length, 2), dtype=np.float32)
    take = min(len(original), length)
    bed[:take] = original[:take].astype(np.float32) / 32768
    speech = np.zeros(length, dtype=np.float32)
    for start_ms, source_end_ms, pcm in placed:
        start = sample_index(start_ms, MIX_RATE)
        end = min(length, max(sample_index(source_end_ms, MIX_RATE), start + len(pcm)))
        if end <= start or end - start < len(pcm):
            raise DubError("dub placement would overrun the source timeline")
        band = bed[start:end]
        # Preserve stereo side information, which often holds room tone/music.
        # Mono or center-panned music cannot be separated reliably.
        center = band.mean(axis=1, keepdims=True)
        fade = min(MIX_RATE // 55, len(band) // 2)
        envelope = np.ones(len(band), dtype=np.float32)
        if fade:
            ramp = np.linspace(0, 1, fade, dtype=np.float32)
            envelope[:fade], envelope[-fade:] = ramp, ramp[::-1]
        residual = (0.65 * (band - center) if channels > 1 else 0)
        band[:] = band * (1 - envelope[:, None]) + residual * envelope[:, None]
        speech[start:start + len(pcm)] = pcm.astype(np.float32) / 32768
    raw = np.asarray(speech * 32767, dtype="<i2")
    before = loudness(raw) if placed else None
    if before is not None:
        peak = float(np.max(np.abs(speech)))
        gain = min(10 ** ((-16 - before) / 20), .83 / max(.00001, peak))
        speech *= gain
    mix = bed + speech[:, None]
    peak = float(np.max(np.abs(mix))) if len(mix) else 0.
    final_gain = min(1., .96 / max(0.001, peak))
    rendered = np.asarray(np.clip(mix * final_gain, -1, 1) * 32767, dtype="<i2")
    actual = loudness(np.asarray(speech * final_gain * 32767, dtype="<i2")) if placed else None
    return rendered, actual


def mux(source, info, audio, subtitles, language, out, duration_ms):
    lang_tags = {"en": "eng", "hi": "hin", "bn": "ben", "mr": "mar", "te": "tel", "ta": "tam",
                 "gu": "guj", "kn": "kan", "ml": "mal", "or": "ori", "pa": "pan", "as": "asm", "ur": "urd"}
    has_subtitles = subtitles.is_file() and subtitles.stat().st_size > 0
    args = ["-i", source, "-i", audio]
    if has_subtitles:
        args += ["-i", subtitles]
    args += ["-map", f"0:{info['video_index']}", "-map", "1:a:0"]
    if has_subtitles:
        args += ["-map", "2:s:0", "-c:s", "mov_text", "-metadata:s:s:0", f"language={lang_tags[language]}"]
    args += ["-c:a", "aac", "-b:a", "160k", "-metadata:s:a:0", f"language={lang_tags[language]}",
             "-metadata:s:a:0", "handler_name=AI-dubbed audio",
             "-metadata", f"title=AI-dubbed ({language})", "-metadata", "comment=AI-dubbed using Bodhan",
             "-t", f"{duration_ms / 1000:.3f}", "-movflags", "+faststart"]
    temp = out.with_name(out.stem + ".part.mp4")
    try:
        try:
            ffmpeg(*args, "-c:v", "copy", temp)
            method = "copy"
        except DubError:
            ffmpeg(*args, "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", temp)
            method = "h264"
        duration = probe(temp)["duration_s"]
        temp.replace(out)
        return method, duration
    finally:
        temp.unlink(missing_ok=True)


def srt_timestamp(ms):
    sec, milli = divmod(ms, 1000)
    minute, sec = divmod(sec, 60)
    hour, minute = divmod(minute, 60)
    return f"{hour:02}:{minute:02}:{sec:02},{milli:03}"
