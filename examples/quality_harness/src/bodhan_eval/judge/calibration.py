"""Calibration against human labels and dynamic threshold tuning."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from bodhan_eval.types import (
    CalibrationMetrics,
    CalibrationReport,
    CheckResult,
    ErrorCategory,
    Label,
)

logger = logging.getLogger(__name__)


def _spans_overlap(s1: tuple[int, int] | list[int] | None, s2: tuple[int, int] | list[int] | None) -> bool:
    """Check if two character spans overlap."""
    if not s1 or not s2:
        return True  # If span is omitted, consider matched if category matches
    start1, end1 = s1[0], s1[1]
    start2, end2 = s2[0], s2[1]
    return max(start1, start2) < min(end1, end2)


class Calibrator:
    """
    Evaluates detector performance against gold ground-truth labels and
    calibrates per-category confidence thresholds to optimize F1 scores.
    """

    def load_labels(self, path: str | Path) -> dict[str, list[Label]]:
        """Load human or gold labels from a JSONL file."""
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"Labels file not found: {file_path}")

        label_map: dict[str, list[Label]] = {}
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                item_id = data.get("id")
                raw_labels = data.get("labels", [])
                if item_id:
                    parsed = []
                    for lbl in raw_labels:
                        try:
                            parsed.append(Label(**lbl))
                        except Exception:
                            pass
                    label_map[item_id] = parsed
        return label_map

    def calibrate(
        self,
        predictions: dict[str, list[CheckResult]],
        ground_truth: dict[str, list[Label]],
        clean_item_ids: set[str] | None = None,
        confidence_thresholds: dict[str, float] | None = None,
    ) -> CalibrationReport:
        """
        Compute precision, recall, F1, localization overlap, and false alarm rate.
        """
        thresholds = confidence_thresholds or {}
        categories = list(ErrorCategory)

        tp_by_cat = {c.value: 0 for c in categories}
        fp_by_cat = {c.value: 0 for c in categories}
        fn_by_cat = {c.value: 0 for c in categories}
        support_by_cat = {c.value: 0 for c in categories}

        overlapping_spans_count = 0
        total_matched_detections = 0
        correct_category_count = 0

        # Tally ground truth support
        for item_id, labels in ground_truth.items():
            for lbl in labels:
                cat = lbl.type.value if hasattr(lbl.type, "value") else str(lbl.type)
                if cat in support_by_cat:
                    support_by_cat[cat] += 1

        # Match predictions against ground truth
        for item_id, gold_labels in ground_truth.items():
            preds = predictions.get(item_id, [])
            # Filter by confidence threshold
            active_preds = [
                p for p in preds
                if not p.passed and p.confidence >= thresholds.get(p.error_type.value if p.error_type else "default", 0.30)
            ]

            unmatched_gold = list(gold_labels)

            for p in active_preds:
                p_cat = p.error_type.value if p.error_type else "unknown"

                # Check if this prediction matches any gold label
                match = None
                for g in unmatched_gold:
                    g_cat = g.type.value if hasattr(g.type, "value") else str(g.type)
                    if g_cat == p_cat or _spans_overlap(p.span, g.span):
                        match = g
                        break

                if match:
                    unmatched_gold.remove(match)
                    g_cat = match.type.value if hasattr(match.type, "value") else str(match.type)
                    if g_cat == p_cat:
                        tp_by_cat[p_cat] = tp_by_cat.get(p_cat, 0) + 1
                        correct_category_count += 1
                    else:
                        fp_by_cat[p_cat] = fp_by_cat.get(p_cat, 0) + 1

                    total_matched_detections += 1
                    if _spans_overlap(p.span, match.span):
                        overlapping_spans_count += 1
                else:
                    if p_cat in fp_by_cat:
                        fp_by_cat[p_cat] += 1

            for g_rem in unmatched_gold:
                g_cat = g_rem.type.value if hasattr(g_rem.type, "value") else str(g_rem.type)
                if g_cat in fn_by_cat:
                    fn_by_cat[g_cat] += 1

        # Calculate per-category metrics
        per_category_metrics: list[CalibrationMetrics] = []
        total_tp = sum(tp_by_cat.values())
        total_fp = sum(fp_by_cat.values())
        total_fn = sum(fn_by_cat.values())

        for c in categories:
            cat_name = c.value
            tp = tp_by_cat[cat_name]
            fp = fp_by_cat[cat_name]
            fn = fn_by_cat[cat_name]
            supp = support_by_cat[cat_name]

            prec = tp / float(tp + fp) if (tp + fp) > 0 else (1.0 if supp == 0 and fp == 0 else 0.0)
            rec = tp / float(tp + fn) if (tp + fn) > 0 else (1.0 if supp == 0 else 0.0)
            f1 = (2 * prec * rec) / float(prec + rec) if (prec + rec) > 0 else 0.0

            if supp > 0 or fp > 0:
                per_category_metrics.append(
                    CalibrationMetrics(
                        category=cat_name,
                        precision=round(prec, 4),
                        recall=round(rec, 4),
                        f1=round(f1, 4),
                        true_positives=tp,
                        false_positives=fp,
                        false_negatives=fn,
                        support=supp,
                    )
                )

        overall_prec = total_tp / float(total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        overall_rec = total_tp / float(total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        overall_f1 = (2 * overall_prec * overall_rec) / float(overall_prec + overall_rec) if (overall_prec + overall_rec) > 0 else 0.0

        loc_acc = overlapping_spans_count / float(total_matched_detections) if total_matched_detections > 0 else 1.0
        cat_acc = correct_category_count / float(total_matched_detections) if total_matched_detections > 0 else 1.0

        # Calculate false alarms on clean items
        fa_rate = 0.0
        if clean_item_ids:
            flagged_clean = 0
            for cid in clean_item_ids:
                flags = [
                    f for f in predictions.get(cid, [])
                    if not f.passed and f.confidence >= thresholds.get(f.error_type.value if f.error_type else "default", 0.30)
                ]
                if flags:
                    flagged_clean += 1
            fa_rate = flagged_clean / float(len(clean_item_ids)) if clean_item_ids else 0.0

        return CalibrationReport(
            per_category=per_category_metrics,
            overall_precision=round(overall_prec, 4),
            overall_recall=round(overall_rec, 4),
            overall_f1=round(overall_f1, 4),
            localization_accuracy=round(loc_acc, 4),
            category_accuracy=round(cat_acc, 4),
            clean_false_alarm_rate=round(fa_rate, 4),
            tuned_thresholds=thresholds,
        )

    def tune_thresholds(
        self,
        predictions: dict[str, list[CheckResult]],
        ground_truth: dict[str, list[Label]],
    ) -> dict[str, float]:
        """
        Grid search optimal confidence thresholds (0.2 to 0.85) to maximize F1 per error category.
        """
        best_thresholds: dict[str, float] = {}
        candidate_values = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]

        for cat in ErrorCategory:
            cat_name = cat.value
            best_f1 = -1.0
            best_thresh = 0.40

            for t in candidate_values:
                trial_thresholds = {c.value: 0.30 for c in ErrorCategory}
                trial_thresholds[cat_name] = t
                report = self.calibrate(predictions, ground_truth, confidence_thresholds=trial_thresholds)
                cat_metric = next((m for m in report.per_category if m.category == cat_name), None)
                if cat_metric and cat_metric.f1 > best_f1:
                    best_f1 = cat_metric.f1
                    best_thresh = t

            best_thresholds[cat_name] = best_thresh

        return best_thresholds
