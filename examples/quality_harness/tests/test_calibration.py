"""Tests for calibration and threshold tuning logic."""

from __future__ import annotations

from bodhan_eval.judge.calibration import Calibrator
from bodhan_eval.types import CheckResult, ErrorCategory, Label


def test_calibration_metrics_calculation():
    calibrator = Calibrator()

    # Ground truth: 2 number errors, 1 format error
    ground_truth = {
        "item-1": [Label(type=ErrorCategory.NUMBER, span=(10, 15))],
        "item-2": [Label(type=ErrorCategory.NUMBER, span=(5, 8))],
        "item-3": [Label(type=ErrorCategory.FORMAT, span=(0, 2))],
        "item-4": [],  # Clean item
    }

    # Predictions:
    # item-1: correctly detected number
    # item-2: missed (false negative)
    # item-3: correctly detected format
    # item-4: false alarm (flagged addition)
    predictions = {
        "item-1": [CheckResult(check_name="test", passed=False, error_type=ErrorCategory.NUMBER, span=(10, 15), confidence=0.9)],
        "item-2": [],
        "item-3": [CheckResult(check_name="test", passed=False, error_type=ErrorCategory.FORMAT, span=(0, 2), confidence=0.85)],
        "item-4": [CheckResult(check_name="test", passed=False, error_type=ErrorCategory.ADDITION, span=None, confidence=0.7)],
    }

    report = calibrator.calibrate(predictions, ground_truth, clean_item_ids={"item-4"})

    # Check overall recall: 2 detected / 3 gold = ~66.7%
    assert 0.60 <= report.overall_recall <= 0.70
    # Localization overlap: both detected have matching spans = 100%
    assert report.localization_accuracy == 1.0
    # Clean false alarm: 1 clean item was flagged = 100%
    assert report.clean_false_alarm_rate == 1.0
