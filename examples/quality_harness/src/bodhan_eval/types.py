"""Data models and type definitions for bodhan_eval."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCategory(str, Enum):
    """Error categories covered by the evaluation harness."""
    OMISSION = "omission"
    ADDITION = "addition"
    MISTRANSLATION = "mistranslation"
    NUMBER = "number"
    ENTITY = "entity"
    FORMAT = "format"
    WRONG_LANGUAGE = "wrong_language"
    SPEECH_OMISSION = "speech_omission"
    SPEECH_REPETITION = "speech_repetition"
    SPEECH_GARBLED = "speech_garbled"


class Severity(str, Enum):
    """Severity ratings for detected errors."""
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class Label(BaseModel):
    """Human or synthetic ground-truth annotation."""
    type: ErrorCategory
    severity: Severity = Severity.MAJOR
    span: tuple[int, int] | list[int] | None = None
    description: str | None = None


class DatasetItem(BaseModel):
    """A single item from a JSONL evaluation dataset."""
    id: str
    source: str
    lang: str
    reference: str | None = None
    translation: str | None = None
    audio: str | bytes | None = None
    labels: list[Label] = Field(default_factory=list)


class CheckResult(BaseModel):
    """The result of running an individual check on an item."""
    check_name: str
    passed: bool
    error_type: ErrorCategory | None = None
    severity: Severity | None = None
    span: tuple[int, int] | list[int] | None = None
    evidence: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)


class ItemReport(BaseModel):
    """Comprehensive evaluation report for a single dataset item."""
    id: str
    lang: str
    source: str
    translation: str | None = None
    audio: str | bytes | None = None
    reference: str | None = None
    checks_run: list[str] = Field(default_factory=list)
    checks_unavailable: dict[str, str] = Field(default_factory=dict)
    flags: list[CheckResult] = Field(default_factory=list)
    score: float = 10.0


class CalibrationMetrics(BaseModel):
    """Precision, recall, and F1 for a specific error category."""
    category: str
    precision: float
    recall: float
    f1: float
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    support: int = 0


class CalibrationReport(BaseModel):
    """Overall calibration performance report against human-labelled items."""
    per_category: list[CalibrationMetrics] = Field(default_factory=list)
    overall_precision: float = 0.0
    overall_recall: float = 0.0
    overall_f1: float = 0.0
    localization_accuracy: float = 0.0
    category_accuracy: float = 0.0
    clean_false_alarm_rate: float = 0.0
    tuned_thresholds: dict[str, float] = Field(default_factory=dict)
