"""Generation of summary.md and summary.json evaluation reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bodhan_eval.types import CalibrationReport, ItemReport


def generate_summary_json(
    item_reports: list[ItemReport],
    calibration: CalibrationReport | None = None,
    cost_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate structured summary.json metrics."""
    total_items = len(item_reports)
    flagged_items = sum(1 for r in item_reports if any(not f.passed for f in r.flags))
    incomplete_items = sum(bool(r.checks_unavailable) for r in item_reports)
    clean_items = sum(not r.checks_unavailable and not any(not f.passed for f in r.flags) for r in item_reports)

    # Per-language breakdown
    by_lang: dict[str, dict[str, Any]] = {}
    for r in item_reports:
        lang = r.lang
        if lang not in by_lang:
            by_lang[lang] = {"total": 0, "flagged": 0, "incomplete": 0, "errors_by_category": {}}
        by_lang[lang]["total"] += 1
        by_lang[lang]["incomplete"] += bool(r.checks_unavailable)
        flags = [f for f in r.flags if not f.passed]
        if flags:
            by_lang[lang]["flagged"] += 1
            for f in flags:
                cat = f.error_type.value if f.error_type else "unknown"
                by_lang[lang]["errors_by_category"][cat] = (
                    by_lang[lang]["errors_by_category"].get(cat, 0) + 1
                )

    # Per-category error totals
    by_category: dict[str, int] = {}
    for r in item_reports:
        for f in r.flags:
            if not f.passed:
                cat = f.error_type.value if f.error_type else "unknown"
                by_category[cat] = by_category.get(cat, 0) + 1

    summary_data: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_items": total_items,
        "clean_items": clean_items,
        "flagged_items": flagged_items,
        "items_with_unavailable_checks": incomplete_items,
        "flag_rate": round(flagged_items / total_items, 4) if total_items > 0 else 0.0,
        "languages": by_lang,
        "errors_by_category": by_category,
        "cost": cost_summary or {},
    }

    if calibration:
        summary_data["calibration"] = calibration.model_dump()

    return summary_data


def generate_summary_md(
    item_reports: list[ItemReport],
    calibration: CalibrationReport | None = None,
    cost_summary: dict[str, Any] | None = None,
    config_dict: dict[str, Any] | None = None,
) -> str:
    """Generate professional, model-team actionable summary.md report."""
    total_items = len(item_reports)
    flagged_items = sum(1 for r in item_reports if any(not f.passed for f in r.flags))
    incomplete_items = sum(bool(r.checks_unavailable) for r in item_reports)
    clean_items = sum(not r.checks_unavailable and not any(not f.passed for f in r.flags) for r in item_reports)
    total_flags = sum(len([f for f in r.flags if not f.passed]) for r in item_reports)

    md = []
    md.append("# Bodhan Quality Evaluation Summary\n")
    md.append(f"**Generated at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  ")
    if config_dict:
        md.append(f"**Dataset:** `{config_dict.get('dataset', 'demo')}` | **Target Languages:** `{config_dict.get('langs', 'all')}`\n")

    # 1. Executive Summary Table
    md.append("## Executive Overview\n")
    md.append("| Metric | Value | Target | Status |")
    md.append("|---|---|---|---|")
    md.append(f"| **Evaluated Items** | {total_items} | — | {'Partial' if incomplete_items else 'Complete'} |")
    md.append(f"| **Clean Items** | {clean_items} ({clean_items / max(1, total_items) * 100:.1f}%) | — | — |")
    md.append(f"| **Items With Unavailable Checks** | {incomplete_items} | 0 | {'Review' if incomplete_items else 'Complete'} |")
    md.append(f"| **Flagged Defect Items** | {flagged_items} ({flagged_items / max(1, total_items) * 100:.1f}%) | — | Audited |")
    md.append(f"| **Total Detected Defects** | {total_flags} | — | — |")

    # Calibration targets if available
    if calibration:
        rec_status = "PASS" if calibration.overall_recall >= 0.80 else "NEEDS REVIEW"
        fa_status = "PASS" if calibration.clean_false_alarm_rate <= 0.10 else "NEEDS REVIEW"
        loc_status = "PASS" if calibration.localization_accuracy >= 0.70 else "NEEDS REVIEW"
        cat_status = "PASS" if calibration.category_accuracy >= 0.70 else "NEEDS REVIEW"

        md.append(f"| **Detection Recall** | {calibration.overall_recall * 100:.1f}% | >= 80% | **{rec_status}** |")
        md.append(f"| **False Alarm Rate** | {calibration.clean_false_alarm_rate * 100:.1f}% | <= 10% | **{fa_status}** |")
        md.append(f"| **Localization Overlap** | {calibration.localization_accuracy * 100:.1f}% | >= 70% | **{loc_status}** |")
        md.append(f"| **Category Accuracy** | {calibration.category_accuracy * 100:.1f}% | >= 70% | **{cat_status}** |")
    md.append("\n")

    # 2. Language Breakdown Table
    md.append("## Language Breakdown\n")
    md.append("| Language | Items | Clean | Flagged | Defect Rate | Top Error Category |")
    md.append("|---|---|---|---|---|---|")

    by_lang: dict[str, list[ItemReport]] = {}
    for r in item_reports:
        by_lang.setdefault(r.lang, []).append(r)

    for lang, reports in sorted(by_lang.items()):
        l_total = len(reports)
        l_flagged = sum(1 for r in reports if any(not f.passed for f in r.flags))
        l_clean = sum(not r.checks_unavailable and not any(not f.passed for f in r.flags) for r in reports)
        l_rate = (l_flagged / l_total * 100) if l_total > 0 else 0.0

        # Find top category
        cat_counts: dict[str, int] = {}
        for r in reports:
            for f in r.flags:
                if not f.passed:
                    cat = f.error_type.value if f.error_type else "unknown"
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
        top_cat = max(cat_counts.items(), key=lambda x: x[1])[0] if cat_counts else "None"

        md.append(f"| **{lang}** | {l_total} | {l_clean} | {l_flagged} | {l_rate:.1f}% | `{top_cat}` |")
    md.append("\n")

    # 3. Error Category Distribution Table
    md.append("## Error Category Distribution\n")
    md.append("| Error Category | Occurrences | Share | Primary Detection Mechanism |")
    md.append("|---|---|---|---|")

    cat_totals: dict[str, int] = {}
    for r in item_reports:
        for f in r.flags:
            if not f.passed:
                cat = f.error_type.value if f.error_type else "unknown"
                cat_totals[cat] = cat_totals.get(cat, 0) + 1

    detection_mechanisms = {
        "omission": "Back-translation + LLM Judge",
        "addition": "Back-translation + LLM Judge",
        "mistranslation": "chrF++ reference / Back-translation + LLM Judge",
        "number": "Indic Numeral Normalization Check (Deterministic)",
        "entity": "Named Entity Heuristic Check (Deterministic)",
        "format": "Markdown & LaTeX Delimiter Integrity Check (Deterministic)",
        "wrong_language": "Script Unicode Range Validator (Deterministic)",
        "speech_omission": "Audio Duration Analysis + Back-transcription",
        "speech_repetition": "N-gram Loop Detector on Back-transcription",
        "speech_garbled": "PCM Waveform RMS Silence & Clipping Analysis",
    }

    for cat, count in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
        share = (count / max(1, total_flags)) * 100.0
        mech = detection_mechanisms.get(cat, "LLM Judge")
        md.append(f"| `{cat}` | {count} | {share:.1f}% | {mech} |")
    md.append("\n")

    # 4. Top Failures (Worst items with evidence)
    md.append("## Top Critical Failures\n")
    worst_reports = sorted(
        [r for r in item_reports if any(not f.passed for f in r.flags)],
        key=lambda r: (
            sum(2 if f.severity and f.severity.value == "critical" else 1 for f in r.flags if not f.passed),
            -r.score
        ),
        reverse=True
    )[:5]

    if worst_reports:
        for i, r in enumerate(worst_reports, start=1):
            md.append(f"### {i}. Item `{r.id}` ({r.lang}) — Score: {r.score:.1f}/10")
            md.append(f"- **Source:** *\"{r.source}\"*")
            if r.translation:
                md.append(f"- **Translation:** *\"{r.translation}\"*")
            md.append("- **Flags:**")
            for f in r.flags:
                if not f.passed:
                    span_str = f" [chars {f.span[0]}:{f.span[1]}]" if f.span else ""
                    sev = f.severity.value.upper() if f.severity else "MAJOR"
                    md.append(f"  - **[{f.error_type.value if f.error_type else 'error'}]** ({sev}{span_str}): {f.evidence}")
            md.append("")
    else:
        md.append("No defects identified across evaluated items.\n")

    # 5. Cost & Computational Efficiency
    if cost_summary:
        md.append("## Model Cost & Resource Utilization\n")
        md.append(f"- **Total Spend:** ₹{cost_summary.get('total_cost_inr', 0.0):.4f} (Budget: ₹{cost_summary.get('max_budget_inr', 50.0):.2f})")
        md.append(f"- **Budget Remaining:** ₹{cost_summary.get('budget_remaining_inr', 0.0):.4f}")
        md.append(f"- **API Operations:** {cost_summary.get('call_count', 0)}")
        breakdown = cost_summary.get("breakdown_by_model_inr", {})
        if breakdown:
            md.append("- **Expenditure by Model:**")
            for model, cost in breakdown.items():
                md.append(f"  - `{model}`: ₹{cost:.4f}")
        md.append("\n")

    # 6. Quality Targets & Known Trade-offs
    md.append("## Audit Targets & Known Limitations\n")
    md.append("- **Noisy Checkers Disambiguation:** Round-trip translation and transcription introduce lexical divergence. Semantic overlap thresholds ensure only true structural omissions or severe distortions trigger flags, while acceptable synonym paraphrasing is tolerated.")
    md.append("- **Script Normalization:** Full Unicode NFC and Indic numeral translation (e.g. '२५' -> '25') prevents false alarms on script numeral variations.")
    md.append("- **Cost Protection:** Audio synthesis is constrained to items flagged for audio validation or explicit generation requests, ensuring runs remain well under the ₹50 budget.")

    return "\n".join(md)
