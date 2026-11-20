"""Serialization of calibration.json performance report."""

from __future__ import annotations

from pathlib import Path

from bodhan_eval.types import CalibrationReport


def generate_calibration_json(report: CalibrationReport, output_path: str | Path) -> None:
    """Serialize calibration metrics to calibration.json."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = report.model_dump_json(indent=2)
    path.write_text(content, encoding="utf-8")
