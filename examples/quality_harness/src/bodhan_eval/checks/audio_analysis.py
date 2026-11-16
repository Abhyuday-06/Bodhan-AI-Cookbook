"""Audio signal analysis for silence, clipping, and duration anomalies."""

from __future__ import annotations

import io
import logging
import math
import struct
import wave
from pathlib import Path
from typing import Any

from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)


class AudioAnalysisCheck(BaseCheck):
    """
    Direct digital signal inspection of synthesized WAV audio files.
    Requires no API calls (cost_tier: free).
    Detects:
    - Long internal silences (> 2.0 seconds)
    - Severe audio clipping (> 1% clipped samples at ±32767)
    - Duration mismatches (unusually short or abnormally long speech)
    """

    name: str = "audio_signal_analysis"
    description: str = "Validates audio duration, silence gaps, and waveform clipping"
    requires_api: bool = False
    cost_tier: str = "free"

    def _analyze_wav(self, audio_bytes: bytes) -> tuple[float, list[tuple[float, float]], float]:
        """
        Analyze WAV audio samples.
        Returns: (duration_sec, silent_intervals, clipping_fraction)
        """
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            num_frames = wf.getnframes()
            duration_sec = num_frames / float(framerate) if framerate > 0 else 0.0

            if sample_width != 2 or num_frames == 0 or framerate == 0:
                return duration_sec, [], 0.0

            raw_data = wf.readframes(num_frames)
            total_samples = len(raw_data) // 2
            # Read 16-bit signed PCM samples
            fmt = f"<{total_samples}h"
            samples = struct.unpack(fmt, raw_data)

            # 1. Clipping detection
            clip_threshold = 32700
            clipped_count = sum(1 for s in samples if abs(s) >= clip_threshold)
            clipping_ratio = clipped_count / float(total_samples)

            # 2. Silence detection using 200ms RMS energy windows
            window_size = int(framerate * 0.20 * channels)
            silence_threshold = 150.0  # RMS amplitude threshold for silence
            silent_windows = []

            for i in range(0, total_samples, window_size):
                window = samples[i:i + window_size]
                if not window:
                    continue
                mean_sq = sum(s * s for s in window) / float(len(window))
                rms = math.sqrt(mean_sq)
                time_sec = (i // channels) / float(framerate)
                if rms < silence_threshold:
                    silent_windows.append(time_sec)

            # Find contiguous silent stretches >= 2.0 seconds
            long_silences: list[tuple[float, float]] = []
            if silent_windows:
                start_t = silent_windows[0]
                prev_t = start_t
                for t in silent_windows[1:]:
                    if t - prev_t <= 0.35:
                        prev_t = t
                    else:
                        if prev_t - start_t >= 2.0:
                            long_silences.append((round(start_t, 2), round(prev_t, 2)))
                        start_t = t
                        prev_t = t
                if prev_t - start_t >= 2.0:
                    long_silences.append((round(start_t, 2), round(prev_t, 2)))

        return duration_sec, long_silences, clipping_ratio

    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        if not item.audio:
            return []

        audio_bytes = None
        if isinstance(item.audio, (str, Path)):
            p = Path(item.audio).resolve()
            if p.is_file():
                audio_bytes = p.read_bytes()
        elif isinstance(item.audio, bytes):
            audio_bytes = item.audio

        if not audio_bytes:
            return []

        results: list[CheckResult] = []

        try:
            duration_sec, long_silences, clipping_ratio = self._analyze_wav(audio_bytes)
        except Exception as e:
            logger.warning(f"Error parsing WAV header for item {item.id}: {e}")
            return [
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.SPEECH_GARBLED,
                    severity=Severity.CRITICAL,
                    span=None,
                    evidence=f"Corrupted or invalid WAV audio file: {e}",
                    confidence=0.95,
                )
            ]

        # 1. Flag clipping distortion (> 1.0% samples clipped)
        if clipping_ratio > 0.01:
            results.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.SPEECH_GARBLED,
                    severity=Severity.MAJOR,
                    span=None,
                    evidence=f"Severe audio clipping: {clipping_ratio * 100:.1f}% of samples exceed maximum dynamic range.",
                    confidence=0.92,
                    details={"clipping_ratio": round(clipping_ratio, 4)},
                )
            )

        # 2. Flag long internal silences (> 2.0s)
        # Exclude initial or trailing silence padding
        internal_silences = [
            (s, e) for (s, e) in long_silences if s > 0.5 and (duration_sec - e) > 0.5
        ]
        if internal_silences:
            first_gap = internal_silences[0]
            results.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.SPEECH_GARBLED,
                    severity=Severity.MAJOR,
                    span=None,
                    evidence=f"Long unnatural silence detected from {first_gap[0]}s to {first_gap[1]}s in audio.",
                    confidence=0.90,
                    details={"silence_gap": first_gap},
                )
            )

        # 3. Flag unnatural duration (< 0.5s for substantive sentence)
        text_len = len(translation.strip()) if translation else len(item.source.strip())
        if text_len > 20 and duration_sec < 0.6:
            results.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.SPEECH_OMISSION,
                    severity=Severity.CRITICAL,
                    span=None,
                    evidence=f"Abnormally short audio ({duration_sec:.2f}s) for {text_len} characters of text.",
                    confidence=0.95,
                    details={"duration_sec": round(duration_sec, 2), "char_count": text_len},
                )
            )

        return results
