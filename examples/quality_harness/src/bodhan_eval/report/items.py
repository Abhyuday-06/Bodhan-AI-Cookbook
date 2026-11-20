"""Generation of items.jsonl detailed per-item evaluation logs."""

from __future__ import annotations

import json
from pathlib import Path

from bodhan_eval.types import ItemReport


def generate_items_jsonl(item_reports: list[ItemReport], output_path: str | Path) -> None:
    """
    Serialize all item evaluation records to JSONL.
    Each row contains:
    - id, lang, source, translation, audio, checks_run
    - flags: list of detected errors with category, severity, span, and evidence
    - score: aggregate quality score
    """
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        for r in item_reports:
            record = {
                "id": r.id,
                "lang": r.lang,
                "source": r.source,
                "translation": r.translation,
                "audio": str(r.audio) if isinstance(r.audio, str) else ("<audio_bytes>" if r.audio else None),
                "reference": r.reference,
                "checks_run": r.checks_run,
                "checks_unavailable": r.checks_unavailable,
                "flags": [
                    {
                        "category": f.error_type.value if f.error_type else "unknown",
                        "severity": f.severity.value if f.severity else "major",
                        "span": list(f.span) if f.span else None,
                        "evidence": f.evidence,
                        "confidence": round(f.confidence, 4),
                        "check_name": f.check_name,
                    }
                    for f in r.flags
                    if not f.passed
                ],
                "score": round(r.score, 2),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
