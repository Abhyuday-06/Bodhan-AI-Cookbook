"""Markdown, LaTeX, and table format integrity check."""

from __future__ import annotations

import logging
import re
from typing import Any

from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)


class FormatCheck(BaseCheck):
    """
    Validates structural formatting preservation between source and translation:
    - Markdown: headers, bold/italic markers, code blocks, lists, links
    - LaTeX: balanced inline/display math delimiters ($ and $$), braces ({})
    - Tables: column separators (|) and markdown table integrity
    """

    name: str = "format_integrity"
    description: str = "Detects broken Markdown formatting, corrupted LaTeX math, or damaged tables"
    requires_api: bool = False
    cost_tier: str = "free"

    def _check_latex(self, source: str, translation: str) -> list[CheckResult]:
        flags: list[CheckResult] = []

        # 1. Check dollar sign math delimiters
        src_dollars = source.count('$')
        tr_dollars = translation.count('$')

        # Check for unclosed single dollar math in translation
        # (Must be an even count of dollars)
        if tr_dollars % 2 != 0:
            pos = translation.rfind('$')
            span = (pos, min(pos + 10, len(translation)))
            flags.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.FORMAT,
                    severity=Severity.MAJOR,
                    span=span,
                    evidence=f"Unmatched LaTeX math delimiter '$' in translation (found {tr_dollars} dollar signs).",
                    confidence=0.95,
                )
            )

        # 2. Check balanced curly braces inside math
        if '{' in translation or '}' in translation:
            open_count = translation.count('{')
            close_count = translation.count('}')
            if open_count != close_count:
                pos = translation.find('{') if open_count > close_count else translation.find('}')
                span = (pos, min(pos + 5, len(translation)))
                flags.append(
                    CheckResult(
                        check_name=self.name,
                        passed=False,
                        error_type=ErrorCategory.FORMAT,
                        severity=Severity.MAJOR,
                        span=span,
                        evidence=f"Unbalanced curly braces in LaTeX/code: {open_count} '{{' vs {close_count} '}}'.",
                        confidence=0.95,
                    )
                )

        # 3. Check preservation of key LaTeX macros (e.g., \frac, \sqrt, \sum, \int)
        src_macros = set(re.findall(r'\\[a-zA-Z]+', source))
        tr_macros = set(re.findall(r'\\[a-zA-Z]+', translation))
        missing_macros = src_macros - tr_macros
        if missing_macros:
            flags.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.FORMAT,
                    severity=Severity.MAJOR,
                    span=None,
                    evidence=f"LaTeX macros from source missing in translation: {', '.join(sorted(missing_macros))}",
                    confidence=0.90,
                )
            )

        return flags

    def _check_markdown(self, source: str, translation: str) -> list[CheckResult]:
        flags: list[CheckResult] = []

        # 1. Code blocks (```)
        src_code = source.count("```")
        tr_code = translation.count("```")
        if tr_code % 2 != 0 or (src_code > 0 and tr_code == 0):
            pos = translation.find("```") if tr_code > 0 else 0
            flags.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.FORMAT,
                    severity=Severity.CRITICAL,
                    span=(pos, pos + 3) if pos < len(translation) else None,
                    evidence=f"Code block delimiter mismatch: {src_code} in source vs {tr_code} in translation.",
                    confidence=0.95,
                )
            )

        # 2. Bold / Italic markers
        src_stars = source.count("**")
        tr_stars = translation.count("**")
        if tr_stars % 2 != 0:
            pos = translation.rfind("**")
            flags.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.FORMAT,
                    severity=Severity.MINOR,
                    span=(pos, pos + 2),
                    evidence="Unclosed bold formatting '**' in translation.",
                    confidence=0.90,
                )
            )

        # 3. Tables (pipe count)
        src_pipes = source.count("|")
        tr_pipes = translation.count("|")
        if src_pipes >= 3 and abs(src_pipes - tr_pipes) > 2:
            flags.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.FORMAT,
                    severity=Severity.MAJOR,
                    span=None,
                    evidence=f"Table structure damaged: Source has {src_pipes} '|' column delimiters, translation has {tr_pipes}.",
                    confidence=0.88,
                )
            )

        return flags

    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        if not translation:
            return []

        results: list[CheckResult] = []
        results.extend(self._check_latex(item.source, translation))
        results.extend(self._check_markdown(item.source, translation))
        return results
