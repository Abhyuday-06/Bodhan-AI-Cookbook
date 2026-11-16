"""Number, digit, quantity, and unit preservation check."""

from __future__ import annotations

import logging
from typing import Any

from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.normalize import extract_numbers
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)


class NumberCheck(BaseCheck):
    """
    Verifies that all numbers, dates, quantities, and percentages from the source
    are accurately preserved in the translation across any Indic numeral script.
    """

    name: str = "number_preservation"
    description: str = "Detects modified, omitted, or hallucinated numbers or units"
    requires_api: bool = False
    cost_tier: str = "free"

    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        if not translation:
            return []

        source_numbers = extract_numbers(item.source)
        trans_numbers = extract_numbers(translation)

        # If no numbers in source, check if hallucinated numbers appeared
        if not source_numbers:
            if trans_numbers:
                first = trans_numbers[0]
                return [
                    CheckResult(
                        check_name=self.name,
                        passed=False,
                        error_type=ErrorCategory.NUMBER,
                        severity=Severity.MAJOR,
                        span=first.span,
                        evidence=f"Hallucinated number '{first.raw}' appears in translation but was not in source.",
                        confidence=0.90,
                    )
                ]
            return []

        # Map numbers by numeric value to find mismatches
        src_vals = [m.numeric_value for m in source_numbers]
        tr_vals = [m.numeric_value for m in trans_numbers]

        results: list[CheckResult] = []

        # Find numbers in source missing from translation
        unmatched_src = []
        remaining_tr_vals = list(tr_vals)
        for s_match in source_numbers:
            val = s_match.numeric_value
            if val in remaining_tr_vals:
                remaining_tr_vals.remove(val)
            else:
                unmatched_src.append(s_match)

        # If there are mismatched numbers
        if unmatched_src:
            for s_miss in unmatched_src:
                # Check if a substitute number exists nearby in translation
                closest_span = None
                evidence_msg = f"Source number '{s_miss.raw}' is missing in translation."
                if trans_numbers:
                    # Provide span of an altered number in translation
                    closest_span = trans_numbers[0].span
                    evidence_msg = (
                        f"Expected number '{s_miss.raw}' from source, but found '{trans_numbers[0].raw}'."
                    )

                results.append(
                    CheckResult(
                        check_name=self.name,
                        passed=False,
                        error_type=ErrorCategory.NUMBER,
                        severity=Severity.MAJOR,
                        span=closest_span,
                        evidence=evidence_msg,
                        confidence=0.95,
                    )
                )

        return results
