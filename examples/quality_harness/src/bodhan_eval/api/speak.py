"""Indic-Speak client for text-to-speech audio synthesis."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from bodhan_eval.cache import DiskCache
from bodhan_eval.concurrency import AsyncRateLimiter, CostTracker, retry_with_backoff

logger = logging.getLogger(__name__)

DEFAULT_VOICES: dict[str, str] = {
    "as": "Prastuti",
    "bn": "Ishita",
    "brx": "Gwrbw",
    "doi": "Preeti",
    "en": "Amit",
    "gu": "Dhara",
    "hi": "Kavya",
    "kn": "Deepika",
    "kok": "Anjali",
    "ks": "Zoon",
    "mai": "Vaidehi",
    "ml": "Lakshmi",
    "mni": "Thoibi",
    "mr": "Anagha",
    "ne": "Srijana",
    "or": "Itishree",
    "pa": "Kaur",
    "sa": "Bharati",
    "sat": "Phulmani",
    "sd": "Moomal",
    "ta": "Anitha",
    "te": "Sravani",
    "ur": "Saba",
}


class SpeakClient:
    """Client for Bodhan Indic-Speak API."""

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

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def synthesize(
        self,
        text: str,
        lang: str,
        voice: str | None = None,
        style: str | None = None,
        output_path: str | Path | None = None,
    ) -> bytes:
        """
        Synthesize text to speech using Indic-Speak.
        Returns WAV audio bytes.
        """
        if not text or not text.strip():
            return b""

        chosen_voice = voice or DEFAULT_VOICES.get(lang.lower(), "Kavya")

        # 1. Check cache first
        cache_params = {"lang": lang, "voice": chosen_voice, "style": style or ""}
        if self.cache:
            cached_audio = self.cache.get_bytes("indic-speak", text, **cache_params)
            if cached_audio:
                logger.debug(f"Cache hit for speech synthesis ({lang})")
                if output_path:
                    p = Path(output_path)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(cached_audio)
                return cached_audio

        # 2. Check cost limits
        if self.cost_tracker and self.cost_tracker.is_over_budget():
            logger.warning("Cost budget reached: Skipping non-cached Indic-Speak call.")
            return b""

        # 3. Call Indic-Speak endpoint
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        instructions: dict[str, str] = {"lang": lang}
        if style:
            instructions["style"] = style

        body = {
            "model": "indic-speak",
            "input": text,
            "voice": chosen_voice,
            "response_format": "wav",
            "instructions": json.dumps(instructions),
        }

        endpoint = f"{self.base_url}/v1/audio/speech"

        async with self.rate_limiter, httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"Indic-Speak error ({resp.status_code})")
            audio_bytes = resp.content
            if not audio_bytes.startswith(b"RIFF"):
                raise RuntimeError("Indic-Speak did not return the requested WAV audio")

        # 4. Record cost
        if self.cost_tracker:
            await self.cost_tracker.record_speech_synthesis(
                input_chars=len(text),
                details=f"Lang: {lang}, Voice: {chosen_voice}"
            )

        # 5. Cache and write
        if self.cache:
            self.cache.set_bytes("indic-speak", text, audio_bytes, **cache_params)

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(audio_bytes)

        return audio_bytes
