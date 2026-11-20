"""Indic-Translate client for translation and back-translation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from bodhan_eval.cache import DiskCache
from bodhan_eval.concurrency import AsyncRateLimiter, CostTracker, retry_with_backoff

logger = logging.getLogger(__name__)


class TranslateClient:
    """Client for Bodhan Indic-Translate API."""

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
        self._route: str | None = None
        self._route_lock = asyncio.Lock()

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str | None = None,
        script: str = "native"
    ) -> str:
        """Translate text into target Indian language or English."""
        if not text or not text.strip():
            return ""

        # 1. Check cache first
        cache_params = {"target_lang": target_lang, "script": script}
        if source_lang:
            cache_params["source_lang"] = source_lang

        if self.cache:
            cached = self.cache.get_json("indic-translate", text, **cache_params)
            if cached and "translation" in cached:
                logger.debug(f"Cache hit for translation to {target_lang}")
                return cached["translation"]

        # 2. Call Bodhan Translate API
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "text": text,
            "target_language": target_lang,
        }
        if target_lang != "en":
            body["script"] = script
        chat_body = {
            "model": "indic-translate",
            "messages": [{"role": "user", "content": text}],
            "target_language_code": target_lang,
        }
        if target_lang != "en":
            chat_body["script"] = script

        async with self.rate_limiter, httpx.AsyncClient(timeout=60.0) as client:
            await self.rate_limiter.wait_for("indic-translate")
            resp = None
            if self._route is None:
                async with self._route_lock:
                    if self._route is None:
                        probe = await client.post(f"{self.base_url}/translate", headers=headers, json=body)
                        if probe.status_code == 404:
                            self._route = "/v1/chat/completions"
                        else:
                            self.rate_limiter.check_response("indic-translate", probe)
                            self._route, resp = "/translate", probe
            if resp is None:
                payload = body if self._route == "/translate" else chat_body
                resp = await client.post(f"{self.base_url}{self._route}", headers=headers, json=payload)
            self.rate_limiter.check_response("indic-translate", resp)
            data = resp.json()

        # Extract translation string
        translated_text = ""
        output_tokens = 0
        if "translation" in data:
            translated_text = data["translation"]
            output_tokens = data.get("usage", {}).get("output_tokens", max(1, len(translated_text) // 4))
        elif "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            if choice.get("finish_reason") in {"length", "max_tokens"}:
                raise RuntimeError("Indic-Translate output was truncated")
            translated_text = choice["message"]["content"]
            output_tokens = data.get("usage", {}).get("completion_tokens", max(1, len(translated_text) // 4))
        else:
            raise ValueError("Unexpected response structure from Indic-Translate")
        if data.get("truncated") or not isinstance(translated_text, str) or not translated_text.strip():
            raise RuntimeError("Indic-Translate returned empty or truncated text")

        # Record cost
        if self.cost_tracker:
            await self.cost_tracker.record_translation(
                output_tokens=output_tokens,
                details=f"to {target_lang}"
            )

        # Cache result
        if self.cache:
            self.cache.set_json(
                "indic-translate",
                text,
                {"translation": translated_text, "output_tokens": output_tokens},
                **cache_params
            )

        return translated_text

    async def back_translate(self, text: str, source_lang: str) -> str:
        """Translate Indic text back to English ('en')."""
        return await self.translate(text=text, target_lang="en", source_lang=source_lang)
