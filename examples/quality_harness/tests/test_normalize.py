"""Tests for Unicode, Indic numeral, and punctuation normalization."""

from __future__ import annotations

from bodhan_eval.normalize import (
    extract_numbers,
    normalize_for_comparison,
    normalize_indic_numerals,
    normalize_punctuation,
)


def test_indic_numeral_normalization():
    # Devanagari ०-९
    assert normalize_indic_numerals("१०० डिग्री") == "100 डिग्री"
    assert normalize_indic_numerals("वर्ष २०२६") == "वर्ष 2026"
    assert normalize_indic_numerals("२५% छूट") == "25% छूट"

    # Bengali ০-৯
    assert normalize_indic_numerals("১০০ ডিগ্রি") == "100 ডিগ্রি"
    assert normalize_indic_numerals("২০২৬ সাল") == "2026 সাল"

    # Tamil ௦-௯
    assert normalize_indic_numerals("௧௦௦ டிகிரி") == "100 டிகிரி"

    # Gujarati ૦-૯
    assert normalize_indic_numerals("૧૦૦") == "100"

    # Gurmukhi ੦-੯
    assert normalize_indic_numerals("੧੦੦") == "100"


def test_punctuation_normalization():
    # Devanagari Danda
    assert normalize_punctuation("यह एक परीक्षण है।") == "यह एक परीक्षण है."
    assert normalize_punctuation("॥ पूर्ण विराम ॥") == ". पूर्ण विराम ."
    # Smart quotes and dashes
    assert normalize_punctuation("‘single’ “double” — dash") == "'single' \"double\" - dash"


def test_extract_numbers():
    text = "The boiling point is 100 °C at sea level with 25% salinity."
    matches = extract_numbers(text)
    assert len(matches) == 2
    assert matches[0].normalized == "100"
    assert matches[0].numeric_value == 100.0
    assert matches[0].span == (21, 24)

    assert matches[1].normalized == "25%"
    assert matches[1].numeric_value == 0.25

    # Extract Indic numerals while preserving original span
    indic_text = "तापमान १०० डिग्री और २५% है।"
    indic_matches = extract_numbers(indic_text)
    assert len(indic_matches) == 2
    assert indic_matches[0].normalized == "100"
    assert indic_matches[0].numeric_value == 100.0
    assert indic_text[indic_matches[0].span[0]:indic_matches[0].span[1]] == "१००"


def test_normalize_for_comparison():
    raw = "यह  परीक्षण    है।  "
    clean = normalize_for_comparison(raw)
    assert clean == "यह परीक्षण है."
