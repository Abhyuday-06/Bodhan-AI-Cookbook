"""Tests for Markdown, LaTeX, and table format integrity checks."""

from __future__ import annotations

import pytest
from bodhan_eval.checks.format_check import FormatCheck
from bodhan_eval.types import DatasetItem, ErrorCategory


@pytest.mark.asyncio
async def test_format_check_clean_latex():
    check = FormatCheck()
    item = DatasetItem(
        id="fmt-1",
        source="Area is $A = \\pi r^2$.",
        lang="hi",
    )
    # Balanced LaTeX
    flags = await check.run(item, "क्षेत्रफल $A = \\pi r^2$ है।", "hi")
    assert len(flags) == 0


@pytest.mark.asyncio
async def test_format_check_broken_latex_delimiter():
    check = FormatCheck()
    item = DatasetItem(
        id="fmt-2",
        source="Area is $A = \\pi r^2$.",
        lang="hi",
    )
    # Broken single dollar delimiter
    flags = await check.run(item, "क्षेत्रफल $A = \\pi r^2 है।", "hi")
    assert len(flags) >= 1
    assert any(f.error_type == ErrorCategory.FORMAT for f in flags)
    assert any("delimiter" in f.evidence for f in flags)


@pytest.mark.asyncio
async def test_format_check_broken_markdown_bold():
    check = FormatCheck()
    item = DatasetItem(
        id="fmt-3",
        source="This is **important** note.",
        lang="hi",
    )
    # Unclosed bold markdown **
    flags = await check.run(item, "यह **महत्वपूर्ण नोट है।", "hi")
    assert len(flags) >= 1
    assert any(f.error_type == ErrorCategory.FORMAT for f in flags)
    assert any("bold" in f.evidence for f in flags)
