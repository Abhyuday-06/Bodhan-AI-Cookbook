"""OpenAI-compatible LLM judge client."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from bodhan_eval.cache import DiskCache
from bodhan_eval.concurrency import AsyncRateLimiter, retry_with_backoff

logger = logging.getLogger(__name__)


class LLMJudgeClient:
    """Client for any OpenAI-compatible LLM used as evaluation judge."""

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        api_key: str = "",
        cache: DiskCache | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.cache = cache
        self.rate_limiter = rate_limiter or AsyncRateLimiter(5)

    def _extract_json(self, raw_text: str) -> dict[str, Any] | None:
        """Extract and parse JSON object from raw response string."""
        if not raw_text:
            return None
        text = raw_text.strip()
        # Direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Extract from markdown ```json ... ``` blocks
        block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if block_match:
            try:
                return json.loads(block_match.group(1))
            except json.JSONDecodeError:
                pass

        # Find first '{' and last '}'
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(text[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to extract JSON from LLM output: {raw_text[:200]}...")
        return None

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def judge(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any] | None:
        """
        Query the LLM judge and return structured JSON assessment.
        Results are cached deterministically.
        """
        # 1. Check cache first
        cache_params = {"model": self.model, "temp": temperature}
        combined_prompt = f"SYS:\n{system_prompt}\n\nUSER:\n{user_prompt}"
        if use_cache and self.cache:
            cached = self.cache.get_json("llm-judge", combined_prompt, **cache_params)
            if cached is not None:
                logger.debug("Cache hit for LLM Judge verdict")
                return cached

        if not self.api_key:
            logger.debug("No LLM_API_KEY provided; returning empty evaluation.")
            return None

        # 2. Call OpenAI-compatible chat completions endpoint
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        endpoint = f"{self.base_url}/chat/completions"

        async with self.rate_limiter, httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            if resp.status_code == 400 and "response_format" in resp.text:
                # Some OpenAI-compatible servers do not support response_format
                body.pop("response_format", None)
                resp = await client.post(endpoint, headers=headers, json=body)

            if resp.status_code != 200:
                raise RuntimeError(f"LLM API error ({resp.status_code}): {resp.text}")

            res_json = resp.json()

        choices = res_json.get("choices", [])
        if not choices:
            return None

        content = choices[0].get("message", {}).get("content", "")
        parsed = self._extract_json(content)

        # 3. Cache valid structured verdict
        if parsed is not None and use_cache and self.cache:
            self.cache.set_json("llm-judge", combined_prompt, parsed, **cache_params)

        return parsed
