"""bodhan_eval: Translation and speech quality evaluation harness for Bodhan AI Indic models."""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "Abhyuday"

from bodhan_eval.config import Config
from bodhan_eval.orchestrator import Orchestrator
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, ItemReport, Severity

__all__ = [
    "CheckResult",
    "Config",
    "DatasetItem",
    "ErrorCategory",
    "ItemReport",
    "Orchestrator",
    "Severity",
    "__version__",
]
