"""Dataset loading, validation, and JSONL serialization."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bodhan_eval.types import DatasetItem, ItemReport, Label

logger = logging.getLogger(__name__)


def read_dataset(path: str | Path) -> tuple[list[DatasetItem], int]:
    """
    Load a JSONL dataset.
    Logs and skips corrupted lines or items missing required fields ('id', 'source', 'lang').
    Returns (valid_items, skipped_count).
    """
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    valid_items: list[DatasetItem] = []
    skipped_count = 0

    with open(file_path, encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as err:
                logger.warning(f"Line {line_no} in {file_path.name}: Malformed JSON - {err}. Skipping.")
                skipped_count += 1
                continue

            if not isinstance(data, dict):
                logger.warning(f"Line {line_no} in {file_path.name}: Not a JSON object. Skipping.")
                skipped_count += 1
                continue

            # Check mandatory fields
            missing = [k for k in ("id", "source", "lang") if k not in data or not str(data[k]).strip()]
            if missing:
                logger.warning(f"Line {line_no} in {file_path.name}: Missing required field(s) {missing}. Skipping.")
                skipped_count += 1
                continue

            # Parse optional labels safely
            raw_labels = data.get("labels", [])
            parsed_labels = []
            if isinstance(raw_labels, list):
                for lbl in raw_labels:
                    if isinstance(lbl, dict) and "type" in lbl:
                        try:
                            parsed_labels.append(Label(**lbl))
                        except Exception as parse_err:
                            logger.debug(f"Line {line_no}: Ignored invalid label {lbl}: {parse_err}")

            data["labels"] = parsed_labels

            try:
                item = DatasetItem(**data)
                valid_items.append(item)
            except Exception as e:
                logger.warning(f"Line {line_no} in {file_path.name}: Validation error: {e}. Skipping.")
                skipped_count += 1

    logger.info(f"Loaded {len(valid_items)} items from {file_path.name} (skipped {skipped_count} invalid).")
    return valid_items, skipped_count


def filter_by_langs(items: list[DatasetItem], target_langs: list[str]) -> list[DatasetItem]:
    """Filter dataset items by target language codes."""
    if not target_langs:
        return items
    allowed = {lang.strip().lower() for lang in target_langs}
    return [item for item in items if item.lang.strip().lower() in allowed]


def write_items_jsonl(reports: list[ItemReport], output_path: str | Path) -> None:
    """Serialize evaluated ItemReports to JSONL."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(r.model_dump_json(exclude_none=True) + "\n" for r in reports)
    logger.info(f"Wrote {len(reports)} item reports to {path}")
