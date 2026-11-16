"""Base class definition for all evaluation checks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from bodhan_eval.types import CheckResult, DatasetItem


class BaseCheck(ABC):
    """Abstract base class for all translation and speech quality checks."""

    name: str = "base_check"
    description: str = "Base quality check"
    requires_api: bool = False
    cost_tier: str = "free"  # "free", "cheap", "expensive"

    @abstractmethod
    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        """
        Execute check against item and its translation.
        Returns a list of CheckResult flags (empty if passed).
        """
        raise NotImplementedError
