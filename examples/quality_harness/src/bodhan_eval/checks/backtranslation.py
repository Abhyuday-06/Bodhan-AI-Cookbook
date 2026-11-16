"""Reference-free translation evaluation via Indic-Translate back-translation."""

from __future__ import annotations

import logging
import re
from typing import Any

from bodhan_eval.api.translate import TranslateClient
from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences by common punctuation."""
    if not text:
        return []
    # Split by period, exclamation, question mark, or Devanagari danda
    parts = re.split(r'[.!?\u0964\u0965]+\s*', text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _word_tokens(text: str) -> set[str]:
    """Extract lowercase alphanumeric word tokens."""
    return set(re.findall(r'\b[a-zA-Z0-9]+\b', text.lower()))


class BackTranslationCheck(BaseCheck):
    """
    Evaluates translation quality without a reference by round-tripping
    the Indic translation back to English using Bodhan's Indic-Translate.

    Carefully isolates checker paraphrasing noise from true model defects:
    - Omission: A complete source sentence is missing from back-translation.
    - Addition: Substantive content exists in back-translation that has no source origin.
    - Mistranslation: Severe divergence in meaning between aligned sentences.
    """

    name: str = "back_translation"
    description: str = "Reference-free semantic verification via round-trip back-translation"
    requires_api: bool = True
    cost_tier: str = "cheap"

    def _sentence_jaccard(self, s1: str, s2: str) -> float:
        w1 = _word_tokens(s1)
        w2 = _word_tokens(s2)
        if not w1 or not w2:
            return 0.0
        return len(w1.intersection(w2)) / len(w1.union(w2))

    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        if not translation or not translation.strip():
            return []

        translate_client: TranslateClient | None = context.get("translate_client")
        if not translate_client:
            logger.debug("No translate client available; skipping back-translation check.")
            return []

        try:
            back_translated = await translate_client.back_translate(
                text=translation,
                source_lang=lang
            )
        except Exception as e:
            logger.warning(f"Back-translation failed for item {item.id}: {e}")
            return []

        if not back_translated:
            return []

        results: list[CheckResult] = []
        src_sentences = _split_sentences(item.source)
        bt_sentences = _split_sentences(back_translated)

        if not src_sentences or not bt_sentences:
            return []

        # 1. Detect OMISSION: source sentence has no plausible match in back-translation
        for s_idx, src_s in enumerate(src_sentences):
            best_score = max((self._sentence_jaccard(src_s, bt_s) for bt_s in bt_sentences), default=0.0)

            # If a source sentence has virtually zero lexical overlap in round trip
            if best_score < 0.15 and len(src_s.split()) >= 4:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        passed=False,
                        error_type=ErrorCategory.OMISSION,
                        severity=Severity.MAJOR,
                        span=None,
                        evidence=(
                            f"Omission detected: Source sentence '{src_s}' is absent in back-translation. "
                            f"(Best round-trip similarity: {best_score:.2f})."
                        ),
                        confidence=0.85,
                        details={"source_sentence": src_s, "back_translation": back_translated},
                    )
                )

        # 2. Detect ADDITION: back-translation sentence has no source match
        for bt_idx, bt_s in enumerate(bt_sentences):
            best_score = max((self._sentence_jaccard(bt_s, src_s) for src_s in src_sentences), default=0.0)

            # Substantive sentence in back-translation with no source basis
            if best_score < 0.12 and len(bt_s.split()) >= 5:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        passed=False,
                        error_type=ErrorCategory.ADDITION,
                        severity=Severity.MAJOR,
                        span=None,
                        evidence=(
                            f"Hallucination / Addition detected: Back-translated sentence '{bt_s}' "
                            f"has no correspondence in source text."
                        ),
                        confidence=0.80,
                        details={"added_sentence": bt_s, "back_translation": back_translated},
                    )
                )

        # 3. Detect MISTRANSLATION: single-sentence items with low alignment
        if len(src_sentences) == 1 and len(bt_sentences) == 1:
            score = self._sentence_jaccard(src_sentences[0], bt_sentences[0])
            if 0.15 <= score < 0.30 and len(src_sentences[0].split()) >= 4:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        passed=False,
                        error_type=ErrorCategory.MISTRANSLATION,
                        severity=Severity.MAJOR,
                        span=None,
                        evidence=(
                            f"Potential mistranslation: Semantic overlap between source and back-translation is low "
                            f"({score:.2f}). Source: '{src_sentences[0]}', Back-translation: '{bt_sentences[0]}'."
                        ),
                        confidence=0.75,
                        details={"source": src_sentences[0], "back_translation": bt_sentences[0]},
                    )
                )

        return results
