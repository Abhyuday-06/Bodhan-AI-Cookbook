"""Registry and exports for all evaluation checks."""

from __future__ import annotations

from bodhan_eval.checks.audio_analysis import AudioAnalysisCheck
from bodhan_eval.checks.backtranslation import BackTranslationCheck
from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.checks.entities import EntityCheck
from bodhan_eval.checks.format_check import FormatCheck
from bodhan_eval.checks.numbers import NumberCheck
from bodhan_eval.checks.reference import ReferenceCheck
from bodhan_eval.checks.script import ScriptCheck
from bodhan_eval.checks.speech import SpeechCheck

__all__ = [
    "AudioAnalysisCheck",
    "BackTranslationCheck",
    "BaseCheck",
    "EntityCheck",
    "FormatCheck",
    "NumberCheck",
    "ReferenceCheck",
    "ScriptCheck",
    "SpeechCheck",
    "get_all_checks",
    "get_deterministic_checks",
]


def get_deterministic_checks() -> list[BaseCheck]:
    """Returns free, zero-API checks that run deterministically."""
    return [
        ScriptCheck(),
        FormatCheck(),
        NumberCheck(),
        EntityCheck(),
        ReferenceCheck(),
        AudioAnalysisCheck(),
    ]


def get_all_checks() -> list[BaseCheck]:
    """Returns all available checks ordered from cheapest to most expensive."""
    return [
        ScriptCheck(),
        FormatCheck(),
        NumberCheck(),
        EntityCheck(),
        ReferenceCheck(),
        AudioAnalysisCheck(),
        BackTranslationCheck(),
        SpeechCheck(),
    ]
