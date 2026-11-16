"""Tests for number preservation check."""

from __future__ import annotations

import pytest

from bodhan_eval.checks.numbers import NumberCheck
from bodhan_eval.types import DatasetItem, ErrorCategory


@pytest.mark.asyncio
async def test_number_check_clean():
    check = NumberCheck()
    item = DatasetItem(
        id="test-1",
        source="Water boils at 100 °C at sea level.",
        lang="hi",
    )
    # Correct ASCII numbers
    flags = await check.run(item, "समुद्र तल पर पानी 100 °C पर उबलता है।", "hi")
    assert len(flags) == 0

    # Correct Indic numerals
    flags_indic = await check.run(item, "समुद्र तल पर पानी १०० °C पर उबलता है।", "hi")
    assert len(flags_indic) == 0


@pytest.mark.asyncio
async def test_number_check_mutated_digit():
    check = NumberCheck()
    item = DatasetItem(
        id="test-2",
        source="Water boils at 100 °C at sea level.",
        lang="hi",
    )
    # Mutated number: 100 -> 200
    flags = await check.run(item, "समुद्र तल पर पानी 200 °C पर उबलता है।", "hi")
    assert len(flags) == 1
    assert flags[0].error_type == ErrorCategory.NUMBER
    assert flags[0].span is not None
    assert "100" in flags[0].evidence


@pytest.mark.asyncio
async def test_number_check_omitted_number():
    check = NumberCheck()
    item = DatasetItem(
        id="test-3",
        source="The distance is 500 km.",
        lang="hi",
    )
    # Number omitted completely
    flags = await check.run(item, "दूरी बहुत अधिक है।", "hi")
    assert len(flags) == 1
    assert flags[0].error_type == ErrorCategory.NUMBER
    assert "500" in flags[0].evidence
