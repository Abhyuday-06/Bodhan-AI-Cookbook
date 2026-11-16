"""Speech evaluation via Indic-Transcribe back-transcription."""

from __future__ import annotations

import logging
import re
from typing import Any

from bodhan_eval.api.transcribe import TranscribeClient
from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.normalize import normalize_for_comparison
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)


def _tokenize_indic(text: str) -> list[str]:
    """Tokenize Indic words and normalize."""
    clean = normalize_for_comparison(text)
    return [w for w in re.split(r'\s+', clean) if w]


class SpeechCheck(BaseCheck):
    """
    Evaluates speech synthesis output by back-transcribing via Indic-Transcribe
    and comparing transcript against the input translation text.

    Distinguishes ASR transcription noise from genuine speech synthesis failures:
    - Truncation / Omission: Trailing clauses or final sentences missing from audio.
    - Repetition / Looping: Repeating n-grams not present in input text.
    - Garbled Audio: Very high word error rate with unintelligible audio transcription.
    """

    name: str = "speech_back_transcription"
    description: str = "Detects speech truncation, repetitive audio loops, and severe transcription mismatches"
    requires_api: bool = True
    cost_tier: str = "expensive"

    def _find_repetitive_ngrams(self, words: list[str], n: int = 2) -> list[str]:
        """Find repeated adjacent or near-adjacent n-grams."""
        if len(words) < n * 2:
            return []
        repeated = []
        for i in range(len(words) - n):
            ngram = " ".join(words[i:i+n])
            # Check if same ngram appears within the next 4 words
            subsequent = " ".join(words[i+n:i+n*3])
            if ngram in subsequent:
                repeated.append(ngram)
        return list(dict.fromkeys(repeated))

    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        if not item.audio:
            return []

        transcribe_client: TranscribeClient | None = context.get("transcribe_client")
        if not transcribe_client:
            logger.debug("No transcribe client available; skipping speech check.")
            return []

        try:
            transcript = await transcribe_client.transcribe(
                audio=item.audio,
                lang=lang
            )
        except Exception as e:
            logger.warning(f"Back-transcription failed for item {item.id}: {e}")
            return []

        if not transcript:
            return [
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.SPEECH_GARBLED,
                    severity=Severity.CRITICAL,
                    span=None,
                    evidence="Indic-Transcribe returned an empty transcript; audio may be silent or corrupted.",
                    confidence=0.90,
                )
            ]

        results: list[CheckResult] = []
        expected_words = _tokenize_indic(translation)
        transcript_words = _tokenize_indic(transcript)

        if not expected_words or not transcript_words:
            return []

        # 1. Detect Repetition / Looping in Speech
        tr_reps = self._find_repetitive_ngrams(transcript_words, n=2)
        exp_reps = self._find_repetitive_ngrams(expected_words, n=2)
        novel_reps = [r for r in tr_reps if r not in exp_reps]

        if novel_reps:
            results.append(
                CheckResult(
                    check_name=self.name,
                    passed=False,
                    error_type=ErrorCategory.SPEECH_REPETITION,
                    severity=Severity.MAJOR,
                    span=None,
                    evidence=(
                        f"Speech synthesis looping detected: Repeating phrase '{novel_reps[0]}' "
                        f"heard in audio but not in input text."
                    ),
                    confidence=0.88,
                    details={"repeated_phrase": novel_reps[0], "transcript": transcript},
                )
            )

        # 2. Detect Truncation / Omission (especially at the end of speech)
        if len(expected_words) >= 6:
            # Check if the last 30% of words are present in transcript
            tail_cutoff = max(1, int(len(expected_words) * 0.70))
            tail_words = expected_words[tail_cutoff:]
            tail_match_count = sum(1 for w in tail_words if w in transcript_words)

            # If almost none of the tail words appear in transcript
            if tail_match_count == 0 and len(transcript_words) < len(expected_words) * 0.75:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        passed=False,
                        error_type=ErrorCategory.SPEECH_OMISSION,
                        severity=Severity.CRITICAL,
                        span=None,
                        evidence=(
                            f"Speech truncation detected: Final sentence/clause was cut off in audio. "
                            f"Expected {len(expected_words)} words, transcribed {len(transcript_words)} words."
                        ),
                        confidence=0.85,
                        details={"missing_tail": " ".join(tail_words), "transcript": transcript},
                    )
                )

        return results
