"""bodhan_eval: Translation and speech quality evaluation harness for Bodhan AI Indic models."""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "Abhyuday"

from bodhan_eval.orchestrator import Orchestrator
from bodhan_eval.config import Config
from bodhan_eval.types import DatasetItem, ItemReport, CheckResult, ErrorCategory, Severity

__all__ = [
    "Orchestrator",
    "Config",
    "DatasetItem",
    "ItemReport",
    "CheckResult",
    "ErrorCategory",
    "Severity",
    "__version__",
]
