"""Tests for script and target language integrity checks."""

from __future__ import annotations

import pytest

from bodhan_eval.checks.script import ScriptCheck
from bodhan_eval.types import DatasetItem, ErrorCategory


@pytest.mark.asyncio
async def test_script_check_clean():
    check = ScriptCheck()
    item = DatasetItem(
        id="scr-1",
        source="Water boils at 100 °C.",
        lang="hi",
    )
    # Devanagari script for Hindi
    flags = await check.run(item, "पानी 100 °C पर उबलता है।", "hi")
    assert len(flags) == 0


@pytest.mark.asyncio
async def test_script_check_wrong_script():
    check = ScriptCheck()
    item = DatasetItem(
        id="scr-2",
        source="Water boils at 100 °C.",
        lang="hi",
    )
    # Bengali script supplied for Hindi target language
    flags = await check.run(item, "জল ১০০ °C তাপমাত্রায় ফোটে।", "hi")
    assert len(flags) >= 1
    assert any(f.error_type == ErrorCategory.WRONG_LANGUAGE for f in flags)


@pytest.mark.asyncio
async def test_script_check_untranslated_latin_passage():
    check = ScriptCheck()
    item = DatasetItem(
        id="scr-3",
        source="This paragraph is about scientific laws.",
        lang="hi",
    )
    # Untranslated English passage left in output
    flags = await check.run(item, "यह नियम according to standard international scientific reports मान्य है।", "hi")
    assert len(flags) >= 1
    assert any(f.error_type == ErrorCategory.WRONG_LANGUAGE for f in flags)
    assert any("Untranslated" in f.evidence for f in flags)
