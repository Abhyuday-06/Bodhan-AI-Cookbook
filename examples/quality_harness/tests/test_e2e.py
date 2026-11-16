"""End-to-end integration test on a 10-item dataset."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import pytest

from bodhan_eval.config import Config
from bodhan_eval.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_end_to_end_harness_run():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        dataset_path = tmp_path / "test_data.jsonl"
        calibration_path = tmp_path / "calib_labels.jsonl"
        out_dir = tmp_path / "report"

        # Create 10 items (5 clean, 5 seeded with diverse defects)
        items = [
            # Clean items
            {"id": "e2e-01", "source": "Water boils at 100 °C.", "lang": "hi", "translation": "पानी 100 °C पर उबलता है।"},
            {"id": "e2e-02", "source": "Light travels fast.", "lang": "hi", "translation": "प्रकाश तेजी से यात्रा करता है।"},
            {"id": "e2e-03", "source": "Photosynthesis produces oxygen.", "lang": "hi", "translation": "प्रकाश संश्लेषण ऑक्सीजन का उत्पादन करता है।"},
            {"id": "e2e-04", "source": "Earth orbits the Sun.", "lang": "hi", "translation": "पृथ्वी सूर्य की परिक्रमा करती है।"},
            {"id": "e2e-05", "source": "Area is $A = \\pi r^2$.", "lang": "hi", "translation": "क्षेत्रफल $A = \\pi r^2$ है।"},

            # Defect items
            # 1. Number mutation: 100 -> 250
            {"id": "e2e-06", "source": "Water boils at 100 °C.", "lang": "hi", "translation": "पानी 250 °C पर उबलता है।",
             "labels": [{"type": "number", "severity": "major", "span": [5, 8]}]},
            # 2. LaTeX format defect: unclosed $
            {"id": "e2e-07", "source": "Area is $A = \\pi r^2$.", "lang": "hi", "translation": "क्षेत्रफल $A = \\pi r^2 है।",
             "labels": [{"type": "format", "severity": "major", "span": [7, 10]}]},
            # 3. Wrong script: Bengali script in Hindi item
            {"id": "e2e-08", "source": "Water boils at 100 °C.", "lang": "hi", "translation": "জল ১০০ °C তাপমাত্রায় ফোটে।",
             "labels": [{"type": "wrong_language", "severity": "critical", "span": [0, 20]}]},
            # 4. Untranslated Latin text
            {"id": "e2e-09", "source": "This is a basic rule.", "lang": "hi", "translation": "यह according to international scientific reports नियम है।",
             "labels": [{"type": "wrong_language", "severity": "critical", "span": [3, 40]}]},
            # 5. Missing acronym entity
            {"id": "e2e-10", "source": "ISRO launched the rocket.", "lang": "hi", "translation": "एक संगठन ने रॉकेट लॉन्च किया।",
             "labels": [{"type": "entity", "severity": "major", "span": [0, 10]}]},
        ]

        with open(dataset_path, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")

        with open(calibration_path, "w", encoding="utf-8") as f:
            for it in items:
                if "labels" in it:
                    f.write(json.dumps({"id": it["id"], "labels": it["labels"]}, ensure_ascii=False) + "\n")

        config = Config(
            dataset=str(dataset_path),
            langs="hi",
            out=str(out_dir),
            calibration=str(calibration_path),
            cache_dir=str(tmp_path / ".cache"),
        )

        orchestrator = Orchestrator(config)
        await orchestrator.run()

        # Validate that all expected output files exist
        assert (out_dir / "summary.md").exists()
        assert (out_dir / "summary.json").exists()
        assert (out_dir / "items.jsonl").exists()
        assert (out_dir / "calibration.json").exists()

        # Verify summary.json content
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["total_items"] == 10
        assert summary["flagged_items"] >= 4  # At least 4 of 5 defect items flagged
        assert summary["clean_items"] <= 6

        # Verify calibration.json
        calib = json.loads((out_dir / "calibration.json").read_text(encoding="utf-8"))
        assert "overall_recall" in calib
        assert calib["overall_recall"] >= 0.75  # High recall on deterministic seeded errors
