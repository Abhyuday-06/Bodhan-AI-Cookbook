"""Reference-based evaluation metrics (chrF++ and BLEU)."""

from __future__ import annotations

import logging
from typing import Any

from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)

try:
    import sacrebleu
    HAS_SACREBLEU = True
except ImportError:
    HAS_SACREBLEU = False


class ReferenceCheck(BaseCheck):
    """
    Computes standard MT benchmark metrics (chrF++ and BLEU) when
    a reference translation is supplied in the dataset.
    """

    name: str = "reference_comparison"
    description: str = "Scores translation against gold reference using chrF++ and BLEU"
    requires_api: bool = False
    cost_tier: str = "free"

    def _fallback_chrf(self, hypothesis: str, reference: str, n: int = 6) -> float:
        """Lightweight character n-gram F-score fallback if sacrebleu is absent."""
        if not hypothesis or not reference:
            return 0.0

        def get_char_ngrams(s: str, n_order: int):
            s_clean = s.replace(" ", "")
            return [s_clean[i:i+n_order] for i in range(max(0, len(s_clean) - n_order + 1))]

        hyp_ngrams = set(get_char_ngrams(hypothesis, 4))
        ref_ngrams = set(get_char_ngrams(reference, 4))
        if not hyp_ngrams or not ref_ngrams:
            return 0.0

        overlap = len(hyp_ngrams.intersection(ref_ngrams))
        precision = overlap / len(hyp_ngrams)
        recall = overlap / len(ref_ngrams)
        if precision + recall == 0:
            return 0.0
        return (2 * precision * recall) / (precision + recall)

    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        if not item.reference or not translation:
            return []

        chrf_score = 0.0
        bleu_score = 0.0

        if HAS_SACREBLEU:
            try:
                chrf = sacrebleu.sentence_chrf(translation, [item.reference], word_order=2)
                chrf_score = chrf.score / 100.0  # Normalized to 0.0-1.0

                bleu = sacrebleu.sentence_bleu(translation, [item.reference])
                bleu_score = bleu.score
            except Exception as e:
                logger.warning(f"sacrebleu scoring failed: {e}")
                chrf_score = self._fallback_chrf(translation, item.reference)
        else:
            chrf_score = self._fallback_chrf(translation, item.reference)

        results: list[CheckResult] = []

        # chrF++ threshold: Indic translations below 0.35 indicate substantial divergence
        if chrf_score < 0.35:
            results.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.MISTRANSLATION,
                    severity=Severity.MAJOR if chrf_score > 0.20 else Severity.CRITICAL,
                    span=None,
                    evidence=(
                        f"Low similarity to reference: chrF++={chrf_score * 100:.1f}, BLEU={bleu_score:.1f}. "
                        f"Ref: '{item.reference[:80]}...'"
                    ),
                    confidence=0.85,
                    details={"chrf": round(chrf_score, 4), "bleu": round(bleu_score, 2)},
                )
            )

        return results
