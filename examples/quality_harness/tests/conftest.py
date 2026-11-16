"""Pytest configuration and PYTHONPATH setup."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import pytest

# Ensure src/ is on sys.path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run async test functions using asyncio.run() even if pytest-asyncio plugin is not installed."""
    testfunction = pyfuncitem.obj
    if asyncio.iscoroutinefunction(testfunction):
        asyncio.run(testfunction(*[pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames]))
        return True
    return None
