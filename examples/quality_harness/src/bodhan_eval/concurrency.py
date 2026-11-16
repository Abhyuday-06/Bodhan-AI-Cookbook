"""Concurrency controls, exponential backoff retries, and cost tracking."""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BudgetExceededError(RuntimeError):
    """Raised when evaluation cost exceeds maximum configured budget."""


class AsyncRateLimiter:
    """Semaphore-based concurrency limiter for async requests."""

    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self.active_tasks = 0

    async def __aenter__(self):
        await self.semaphore.acquire()
        self.active_tasks += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.active_tasks -= 1
        self.semaphore.release()


def retry_with_backoff(
    max_retries: int = 4,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: bool = True
):
    """
    Decorator for async functions that handles rate limits (429) and transient server errors.
    """
    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as err:
                    last_err = err
                    err_str = str(err).lower()
                    is_transient = any(code in err_str for code in ["429", "500", "502", "503", "timeout", "connection reset"])
                    if attempt == max_retries or not is_transient:
                        logger.error(f"Non-retryable or max retries reached for {func.__name__}: {err}")
                        raise err

                    sleep_time = delay * (random.uniform(0.8, 1.2) if jitter else 1.0)
                    logger.warning(
                        f"Transient failure on {func.__name__} (attempt {attempt}/{max_retries}): {err}. "
                        f"Retrying in {sleep_time:.2f}s..."
                    )
                    await asyncio.sleep(sleep_time)
                    delay *= backoff_factor
            raise last_err  # type: ignore
        return wrapper
    return decorator


class CostTracker:
    """
    Monitors and bounds API expenditure based on official Bodhan pricing:
    - Indic-Translate: ₹0.20 per 10,000 output tokens (₹0.00002 / token)
    - Indic-Speak: ₹6 per 10,000 input characters (₹0.0006 / char)
    - Indic-Transcribe: ₹0.10 per audio minute (₹0.001667 / sec)
    """

    TRANSLATE_PER_TOKEN = 0.20 / 10000.0
    SPEAK_PER_CHAR = 6.0 / 10000.0
    TRANSCRIBE_PER_SEC = 0.10 / 60.0

    def __init__(self, max_cost_inr: float = 50.0):
        self.max_cost_inr = max_cost_inr
        self.expenses: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def record_translation(self, output_tokens: int, details: str = "") -> float:
        cost = output_tokens * self.TRANSLATE_PER_TOKEN
        await self._add_cost("indic-translate", cost, f"{output_tokens} tokens - {details}")
        return cost

    async def record_speech_synthesis(self, input_chars: int, details: str = "") -> float:
        cost = input_chars * self.SPEAK_PER_CHAR
        await self._add_cost("indic-speak", cost, f"{input_chars} characters - {details}")
        return cost

    async def record_transcription(self, audio_seconds: float, details: str = "") -> float:
        cost = audio_seconds * self.TRANSCRIBE_PER_SEC
        await self._add_cost("indic-transcribe", cost, f"{audio_seconds:.1f}s audio - {details}")
        return cost

    async def _add_cost(self, model: str, amount_inr: float, description: str):
        async with self._lock:
            self.expenses.append({
                "model": model,
                "amount_inr": amount_inr,
                "description": description,
                "timestamp": time.time(),
            })
            total = sum(e["amount_inr"] for e in self.expenses)
            if total > self.max_cost_inr:
                logger.warning(f"Budget exceeded! Total spent: ₹{total:.2f} > Max: ₹{self.max_cost_inr:.2f}")

    def total_cost(self) -> float:
        return sum(e["amount_inr"] for e in self.expenses)

    def is_over_budget(self) -> bool:
        return self.total_cost() >= self.max_cost_inr

    def summary(self) -> dict[str, Any]:
        """Aggregate expenses by model."""
        by_model: dict[str, float] = {}
        for item in self.expenses:
            m = item["model"]
            by_model[m] = by_model.get(m, 0.0) + item["amount_inr"]
        return {
            "total_cost_inr": round(self.total_cost(), 4),
            "max_budget_inr": self.max_cost_inr,
            "budget_remaining_inr": round(max(0.0, self.max_cost_inr - self.total_cost()), 4),
            "breakdown_by_model_inr": {k: round(v, 4) for k, v in by_model.items()},
            "call_count": len(self.expenses),
        }
