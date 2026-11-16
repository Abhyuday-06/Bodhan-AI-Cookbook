"""Indic-Transcribe client for back-transcription and speech-to-text."""

from __future__ import annotations

import io
import logging
import wave
from pathlib import Path
import httpx

from bodhan_eval.cache import DiskCache
from bodhan_eval.concurrency import AsyncRateLimiter, CostTracker, retry_with_backoff

logger = logging.getLogger(__name__)


class TranscribeClient:
    """Client for Bodhan Indic-Transcribe API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.bodhan.ai",
        cache: DiskCache | None = None,
        cost_tracker: CostTracker | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.cost_tracker = cost_tracker
        self.rate_limiter = rate_limiter or AsyncRateLimiter(5)

    def _estimate_wav_duration(self, audio_bytes: bytes) -> float:
        """Read duration in seconds from WAV header."""
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return frames / float(rate)
        except Exception:
            pass
        # Fallback approximation for 16-bit 24kHz mono PCM WAV: ~48,000 bytes/sec
        return max(1.0, len(audio_bytes) / 48000.0)

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def transcribe(
        self,
        audio: str | Path | bytes,
        lang: str | None = None,
    ) -> str:
        """
        Transcribe audio using Indic-Transcribe.
        Accepts file path or raw audio bytes.
        """
        if isinstance(audio, (str, Path)):
            audio_path = Path(audio).resolve()
            if not audio_path.exists():
                logger.error(f"Audio file does not exist: {audio_path}")
                return ""
            audio_bytes = audio_path.read_bytes()
            filename = audio_path.name
        else:
            audio_bytes = audio
            filename = "sample.wav"

        if not audio_bytes:
            return ""

        # 1. Check cache first
        cache_params = {"lang": lang or "auto"}
        if self.cache:
            cached = self.cache.get_json("indic-transcribe", audio_bytes, **cache_params)
            if cached and "text" in cached:
                logger.debug(f"Cache hit for transcription ({lang})")
                return cached["text"]

        # 2. Check cost limits
        if self.cost_tracker and self.cost_tracker.is_over_budget():
            logger.warning("Cost budget reached: Skipping non-cached Indic-Transcribe call.")
            return ""

        duration_sec = self._estimate_wav_duration(audio_bytes)

        # 3. Call Indic-Transcribe endpoint
        headers = {"Authorization": f"Bearer {self.api_key}"}
        endpoint = f"{self.base_url}/v1/audio/transcriptions"

        files = {"file": (filename, audio_bytes, "audio/wav")}
        data: dict[str, str] = {"model": "indic-transcribe"}
        if lang:
            data["language"] = lang

        async with self.rate_limiter:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(endpoint, headers=headers, files=files, data=data)
                if resp.status_code != 200:
                    raise RuntimeError(f"Indic-Transcribe error ({resp.status_code}): {resp.text}")
                result_json = resp.json()

        transcribed_text = result_json.get("text", "")

        # 4. Record cost
        if self.cost_tracker:
            await self.cost_tracker.record_transcription(
                audio_seconds=duration_sec,
                details=f"Lang: {lang or 'detected'}"
            )

        # 5. Cache result
        if self.cache:
            self.cache.set_json(
                "indic-transcribe",
                audio_bytes,
                {"text": transcribed_text, "duration_sec": duration_sec},
                **cache_params
            )

        return transcribed_text
