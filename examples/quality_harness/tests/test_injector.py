"""Tests for programmatic error injector (verifying ground rules: no LLM text generation)."""

from __future__ import annotations

from bodhan_eval.injector.injector import ErrorInjector
from bodhan_eval.types import ErrorCategory


def test_injector_number_mutation():
    injector = ErrorInjector(seed=42)
    clean_text = "तापमान 100 डिग्री है।"
    mutated, label = injector.inject_number_error(clean_text)

    assert label is not None
    assert label.type == ErrorCategory.NUMBER
    assert mutated != clean_text
    assert label.span is not None


def test_injector_format_mutation():
    injector = ErrorInjector(seed=42)
    clean_text = "क्षेत्रफल $A = \\pi r^2$ है।"
    mutated, label = injector.inject_format_error(clean_text)

    assert label is not None
    assert label.type == ErrorCategory.FORMAT
    # The count of dollar signs should have changed
    assert mutated.count("$") != clean_text.count("$")


def test_injector_omission_mutation():
    injector = ErrorInjector(seed=42)
    clean_text = "यह पहला वाक्य है। यह दूसरा वाक्य है। यह तीसरा वाक्य है।"
    mutated, label = injector.inject_omission(clean_text)

    assert label is not None
    assert label.type == ErrorCategory.OMISSION
    assert len(mutated) < len(clean_text)
