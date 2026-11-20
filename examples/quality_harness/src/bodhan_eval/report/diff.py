"""Generation of diff.md comparing evaluation runs against a baseline."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_items_map(report_dir: Path) -> dict[str, dict[str, Any]]:
    """Load items.jsonl from report directory into {item_id: item_dict}."""
    items_path = report_dir / "items.jsonl"
    if not items_path.exists():
        logger.warning(f"No items.jsonl found in {report_dir}")
        return {}

    items_map: dict[str, dict[str, Any]] = {}
    with open(items_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if "id" in data:
                items_map[data["id"]] = data
    return items_map


def generate_diff_md(current_report_dir: str | Path, baseline_report_dir: str | Path) -> str:
    """
    Compare current evaluation run against baseline report directory.
    Identifies improvements, regressions, and category shifts with concrete examples.
    """
    cur_dir = Path(current_report_dir).resolve()
    base_dir = Path(baseline_report_dir).resolve()

    current_items = _load_items_map(cur_dir)
    baseline_items = _load_items_map(base_dir)

    common_ids = set(current_items.keys()).intersection(baseline_items.keys())

    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    unchanged_defects: int = 0
    clean_in_both: int = 0

    for i_id in common_ids:
        cur_flags = current_items[i_id].get("flags", [])
        base_flags = baseline_items[i_id].get("flags", [])

        cur_errors = {f.get("category"): f for f in cur_flags}
        base_errors = {f.get("category"): f for f in base_flags}

        new_cats = set(cur_errors.keys()) - set(base_errors.keys())
        resolved_cats = set(base_errors.keys()) - set(cur_errors.keys())

        if new_cats:
            regressions.append({
                "id": i_id,
                "lang": current_items[i_id].get("lang"),
                "source": current_items[i_id].get("source"),
                "translation": current_items[i_id].get("translation"),
                "new_categories": list(new_cats),
                "flags": [cur_errors[c] for c in new_cats],
            })

        if resolved_cats:
            improvements.append({
                "id": i_id,
                "lang": current_items[i_id].get("lang"),
                "source": current_items[i_id].get("source"),
                "translation": current_items[i_id].get("translation"),
                "resolved_categories": list(resolved_cats),
                "resolved_flags": [base_errors[c] for c in resolved_cats],
            })

        if not cur_flags and not base_flags:
            clean_in_both += 1
        elif cur_flags and base_flags and not new_cats and not resolved_cats:
            unchanged_defects += 1

    md = []
    md.append("# Regression & Diff Report Against Baseline\n")
    md.append(f"**Current Run:** `{cur_dir.name}`  ")
    md.append(f"**Baseline Run:** `{base_dir.name}`  ")
    md.append(f"**Common Evaluated Items:** {len(common_ids)}\n")

    # 1. High-level Shift Summary
    md.append("## Comparative Overview\n")
    md.append("| Status Category | Items Count | % of Common Items |")
    md.append("|---|---|---|")
    md.append(f"| **Clean in Both Runs** | {clean_in_both} | {clean_in_both / max(1, len(common_ids)) * 100:.1f}% |")
    md.append(f"| **Regressed (New Errors)** | **{len(regressions)}** | {len(regressions) / max(1, len(common_ids)) * 100:.1f}% |")
    md.append(f"| **Improved (Errors Fixed)** | **{len(improvements)}** | {len(improvements) / max(1, len(common_ids)) * 100:.1f}% |")
    md.append(f"| **Unchanged Defect Items** | {unchanged_defects} | {unchanged_defects / max(1, len(common_ids)) * 100:.1f}% |")
    md.append("\n")

    # 2. Detailed Regressions
    md.append("## Top Regressions (New Quality Defects)\n")
    if regressions:
        for i, reg in enumerate(regressions[:5], start=1):
            md.append(f"### {i}. Item `{reg['id']}` ({reg['lang']})")
            md.append(f"- **Source:** *\"{reg['source']}\"*")
            md.append(f"- **Current Translation:** *\"{reg['translation']}\"*")
            md.append(f"- **New Defect Categories:** `{', '.join(reg['new_categories'])}`")
            for f in reg["flags"]:
                md.append(f"  - **[{f.get('category')}]** ({f.get('severity', 'major')}): {f.get('evidence')}")
            md.append("")
    else:
        md.append("No regressions detected relative to baseline.\n")

    # 3. Detailed Improvements
    md.append("## Top Improvements (Resolved Errors)\n")
    if improvements:
        for i, imp in enumerate(improvements[:5], start=1):
            md.append(f"### {i}. Item `{imp['id']}` ({imp['lang']})")
            md.append(f"- **Source:** *\"{imp['source']}\"*")
            md.append(f"- **Current Translation:** *\"{imp['translation']}\"*")
            md.append(f"- **Resolved Categories:** `{', '.join(imp['resolved_categories'])}`")
            for f in imp["resolved_flags"]:
                md.append(f"  - Fixed: [{f.get('category')}] {f.get('evidence')}")
            md.append("")
    else:
        md.append("No improvements detected relative to baseline.\n")

    return "\n".join(md)
