"""Tests for named entity preservation check."""

from __future__ import annotations

import pytest

from bodhan_eval.checks.entities import EntityCheck
from bodhan_eval.types import DatasetItem, ErrorCategory


@pytest.mark.asyncio
async def test_entity_check_clean():
    check = EntityCheck()
    item = DatasetItem(
        id="ent-1",
        source="UNESCO was founded to promote cooperation.",
        lang="hi",
    )
    # UNESCO preserved
    flags = await check.run(item, "सहयोग को बढ़ावा देने के लिए UNESCO की स्थापना की गई थी।", "hi")
    assert len(flags) == 0


@pytest.mark.asyncio
async def test_entity_check_missing_acronym():
    check = EntityCheck()
    item = DatasetItem(
        id="ent-2",
        source="UNESCO was founded to promote cooperation.",
        lang="hi",
    )
    # UNESCO dropped completely
    flags = await check.run(item, "सहयोग को बढ़ावा देने के लिए एक संगठन की स्थापना की गई थी।", "hi")
    assert len(flags) == 1
    assert flags[0].error_type == ErrorCategory.ENTITY
    assert "UNESCO" in flags[0].evidence
