"""Unicode, Indic-script, and numeral normalization utilities."""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

# Mapping of all Indic digit Unicode blocks to standard ASCII digits 0-9
INDIC_DIGITS = {
    # Devanagari (Hindi, Marathi, Maithili, Sanskrit, Nepali, Konkani, Kashmiri-Deva)
    '\u0966': '0', '\u0967': '1', '\u0968': '2', '\u0969': '3', '\u096a': '4',
    '\u096b': '5', '\u096c': '6', '\u096d': '7', '\u096e': '8', '\u096f': '9',
    # Bengali / Assamese / Manipuri-Bengali
    '\u09e6': '0', '\u09e7': '1', '\u09e8': '2', '\u09e9': '3', '\u09ea': '4',
    '\u09eb': '5', '\u09ec': '6', '\u09ed': '7', '\u09ee': '8', '\u09ef': '9',
    # Gurmukhi (Punjabi)
    '\u0a66': '0', '\u0a67': '1', '\u0a68': '2', '\u0a69': '3', '\u0a6a': '4',
    '\u0a6b': '5', '\u0a6c': '6', '\u0a6d': '7', '\u0a6e': '8', '\u0a6f': '9',
    # Gujarati
    '\u0ae6': '0', '\u0ae7': '1', '\u0ae8': '2', '\u0ae9': '3', '\u0aea': '4',
    '\u0aeb': '5', '\u0aec': '6', '\u0aed': '7', '\u0aee': '8', '\u0aef': '9',
    # Odia (Oriya)
    '\u0b66': '0', '\u0b67': '1', '\u0b68': '2', '\u0b69': '3', '\u0b6a': '4',
    '\u0b6b': '5', '\u0b6c': '6', '\u0b6d': '7', '\u0b6e': '8', '\u0b6f': '9',
    # Tamil
    '\u0be6': '0', '\u0be7': '1', '\u0be8': '2', '\u0be9': '3', '\u0bea': '4',
    '\u0beb': '5', '\u0bec': '6', '\u0bed': '7', '\u0bee': '8', '\u0bef': '9',
    # Telugu
    '\u0c66': '0', '\u0c67': '1', '\u0c68': '2', '\u0c69': '3', '\u0c6a': '4',
    '\u0c6b': '5', '\u0c6c': '6', '\u0c6d': '7', '\u0c6e': '8', '\u0c6f': '9',
    # Kannada
    '\u0ce6': '0', '\u0ce7': '1', '\u0ce8': '2', '\u0ce9': '3', '\u0cea': '4',
    '\u0ceb': '5', '\u0cec': '6', '\u0ced': '7', '\u0cee': '8', '\u0cef': '9',
    # Malayalam
    '\u0d66': '0', '\u0d67': '1', '\u0d68': '2', '\u0d69': '3', '\u0d6a': '4',
    '\u0d6b': '5', '\u0d6c': '6', '\u0d6d': '7', '\u0d6e': '8', '\u0d6f': '9',
    # Arabic-Indic (Urdu, Kashmiri, Sindhi-Arab)
    '\u0660': '0', '\u0661': '1', '\u0662': '2', '\u0663': '3', '\u0664': '4',
    '\u0665': '5', '\u0666': '6', '\u0667': '7', '\u0668': '8', '\u0669': '9',
    # Eastern Arabic-Indic / Extended Arabic
    '\u06f0': '0', '\u06f1': '1', '\u06f2': '2', '\u06f3': '3', '\u06f4': '4',
    '\u06f5': '5', '\u06f6': '6', '\u06f7': '7', '\u06f8': '8', '\u06f9': '9',
}

_DIGIT_TRANSLATION_TABLE = str.maketrans(INDIC_DIGITS)

# Punctuation translation table
PUNCT_MAP = {
    '\u0964': '.',  # Devanagari Danda -> dot
    '\u0965': '.',  # Devanagari Double Danda
    '\u2018': "'", '\u2019': "'",  # Smart single quotes
    '\u201c': '"', '\u201d': '"',  # Smart double quotes
    '\u2013': '-', '\u2014': '-',  # En/Em dashes
    '\u00a0': ' ',                 # Non-breaking space
    '\u200b': '',                  # Zero-width space
    '\u200c': '',                  # ZWNJ (Zero-width non-joiner)
    '\u200d': '',                  # ZWJ (Zero-width joiner)
}
_PUNCT_TRANSLATION_TABLE = str.maketrans(PUNCT_MAP)


class NumberMatch(NamedTuple):
    raw: str
    normalized: str
    numeric_value: float
    span: tuple[int, int]


def normalize_unicode(text: str, form: str = "NFC") -> str:
    """Normalize Unicode characters to NFC or NFKC."""
    if not text:
        return ""
    return unicodedata.normalize(form, text)


def normalize_indic_numerals(text: str) -> str:
    """Convert any Indic script numeral (०-९, ০-৯, ௦-௯, etc.) to ASCII 0-9."""
    if not text:
        return ""
    return text.translate(_DIGIT_TRANSLATION_TABLE)


def normalize_punctuation(text: str) -> str:
    """Normalize regional and smart punctuation marks."""
    if not text:
        return ""
    return text.translate(_PUNCT_TRANSLATION_TABLE)


def normalize_whitespace(text: str) -> str:
    """Collapse consecutive whitespace and strip edges."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def normalize_for_comparison(text: str, preserve_digits: bool = False) -> str:
    """Full normalization pipeline for comparison."""
    if not text:
        return ""
    text = normalize_unicode(text, "NFKC")
    if not preserve_digits:
        text = normalize_indic_numerals(text)
    text = normalize_punctuation(text)
    text = normalize_whitespace(text)
    return text


def extract_numbers(text: str) -> list[NumberMatch]:
    """
    Extract numbers, decimals, percentages, and quantities with character spans.
    Normalizes Indic numerals while preserving original span offsets.
    """
    if not text:
        return []

    # Map Indic characters to ASCII while keeping original length 1:1
    normalized_chars = [INDIC_DIGITS.get(c, c) for c in text]
    one_to_one_ascii = "".join(normalized_chars)

    # Regex matches numbers, floats, percentages, and year-like patterns
    # e.g., 100, 3.14, -40, 25%, 1,000, 2026
    pattern = re.compile(r'(?<![A-Za-z0-9])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?)(?![A-Za-z0-9])')

    matches: list[NumberMatch] = []
    for m in pattern.finditer(one_to_one_ascii):
        raw_span = (m.start(1), m.end(1))
        raw_token = text[raw_span[0]:raw_span[1]]
        clean_num_str = m.group(1).replace(',', '')
        is_percent = clean_num_str.endswith('%')
        clean_val_str = clean_num_str[:-1] if is_percent else clean_num_str

        try:
            val = float(clean_val_str)
            if is_percent:
                val /= 100.0
            matches.append(NumberMatch(
                raw=raw_token,
                normalized=clean_num_str,
                numeric_value=val,
                span=raw_span
            ))
        except ValueError:
            continue

    return matches


def compute_char_overlap(str1: str, str2: str) -> float:
    """Compute character-level Jaccard similarity between two strings."""
    if not str1 or not str2:
        return 0.0
    set1 = set(str1.lower())
    set2 = set(str2.lower())
    union = set1.union(set2)
    if not union:
        return 0.0
    return len(set1.intersection(set2)) / len(union)
