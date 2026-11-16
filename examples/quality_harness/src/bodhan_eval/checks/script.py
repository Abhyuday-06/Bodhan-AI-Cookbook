"""Script and target language integrity check."""

from __future__ import annotations

import logging
import re
from typing import Any

from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)

# Expected Unicode block ranges for each target language code
SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "hi": (0x0900, 0x097F),       # Devanagari
    "mr": (0x0900, 0x097F),       # Devanagari
    "mai": (0x0900, 0x097F),      # Devanagari
    "ne": (0x0900, 0x097F),       # Devanagari
    "sa": (0x0900, 0x097F),       # Devanagari
    "kok": (0x0900, 0x097F),      # Devanagari
    "ks-deva": (0x0900, 0x097F),  # Devanagari
    "bn": (0x0980, 0x09FF),       # Bengali
    "as": (0x0980, 0x09FF),       # Bengali/Assamese
    "mni-beng": (0x0980, 0x09FF), # Bengali
    "ta": (0x0B80, 0x0BFF),       # Tamil
    "te": (0x0C00, 0x0C7F),       # Telugu
    "kn": (0x0C80, 0x0CFF),       # Kannada
    "ml": (0x0D00, 0x0D7F),       # Malayalam
    "gu": (0x0A80, 0x0AFF),       # Gujarati
    "pa": (0x0A00, 0x0A7F),       # Gurmukhi
    "or": (0x0B00, 0x0B7F),       # Odia
    "ur": (0x0600, 0x06FF),       # Arabic / Perso-Arabic
    "ks": (0x0600, 0x06FF),       # Arabic / Perso-Arabic
    "sd-arab": (0x0600, 0x06FF),  # Arabic / Perso-Arabic
}


class ScriptCheck(BaseCheck):
    """
    Verifies that the translation is rendered in the correct target language script
    and flags untranslated passages or wrong language outputs.
    """

    name: str = "script_and_language"
    description: str = "Detects wrong alphabet/script or untranslated source text"
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

        clean_lang = lang.lower().strip()
        expected_range = SCRIPT_RANGES.get(clean_lang)

        results: list[CheckResult] = []

        # 1. Check for untranslated source text (runs of 5+ Latin words)
        latin_runs = re.findall(r'\b[A-Za-z]+(?:\s+[A-Za-z]+){4,}\b', translation)
        if latin_runs:
            span = None
            first_run = latin_runs[0]
            start_pos = translation.find(first_run)
            if start_pos != -1:
                span = (start_pos, start_pos + len(first_run))

            results.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.WRONG_LANGUAGE,
                    severity=Severity.CRITICAL,
                    span=span,
                    evidence=f"Untranslated English passage left in output: '{first_run[:60]}...'",
                    confidence=0.92,
                )
            )

        # 2. Check for script mismatch if expected range is defined
        if expected_range:
            low, high = expected_range
            # Filter to alphabetic characters (ignore ASCII punctuation, digits, spaces)
            indic_chars = [c for c in translation if ord(c) > 0x0500]
            if indic_chars:
                in_expected_script = sum(1 for c in indic_chars if low <= ord(c) <= high)
                ratio = in_expected_script / len(indic_chars)

                # If less than 60% of Indic characters match the target language script
                if ratio < 0.60:
                    results.append(
                        CheckResult(
                            check_name=self.name,
                            passed=False,
                            error_type=ErrorCategory.WRONG_LANGUAGE,
                            severity=Severity.CRITICAL,
                            span=(0, min(50, len(translation))),
                            evidence=(
                                f"Wrong script detected for language '{lang}'. "
                                f"Only {ratio * 100:.1f}% of characters match expected Unicode block."
                            ),
                            confidence=0.95,
                        )
                    )

        return results
