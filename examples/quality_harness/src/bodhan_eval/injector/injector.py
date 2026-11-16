"""Programmatic error injector for benchmarking and calibration.

CRITICAL GROUND RULE:
All errors in Indian-language text and audio are generated strictly PROGRAMMATICALLY
(by deleting spans, altering digits, modifying formatting, or perturbing signals).
The LLM is NEVER used to write or mutate Indian-language text.
"""

from __future__ import annotations

import io
import logging
import random
import re
import wave

from bodhan_eval.normalize import INDIC_DIGITS
from bodhan_eval.types import DatasetItem, ErrorCategory, Label, Severity

logger = logging.getLogger(__name__)


class ErrorInjector:
    """
    Synthesizes labelled test cases from clean items for testing evaluation recall.
    All transformations are fully deterministic and programmatic.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def inject_number_error(self, text: str) -> tuple[str, Label | None]:
        """Mutate a digit or number in the translation."""
        # Find any ASCII or Indic digit
        matches = list(re.finditer(r'\d', text))
        if not matches:
            # Check for Indic numerals
            indic_pattern = f"[{''.join(INDIC_DIGITS.keys())}]"
            matches = list(re.finditer(indic_pattern, text))

        if not matches:
            return text, None

        target = self.rng.choice(matches)
        start, end = target.start(), target.end()
        orig_char = text[start:end]

        # Mutate the digit
        if orig_char.isdigit():
            new_digit = str((int(orig_char) + self.rng.choice([1, 2, 3, 5])) % 10)
        else:
            # Map Indic digit to altered ASCII digit
            new_digit = str((int(INDIC_DIGITS.get(orig_char, "5")) + 3) % 10)

        mutated_text = text[:start] + new_digit + text[end:]
        label = Label(
            type=ErrorCategory.NUMBER,
            severity=Severity.MAJOR,
            span=(start, start + len(new_digit)),
            description=f"Injected number mutation: '{orig_char}' -> '{new_digit}'"
        )
        return mutated_text, label

    def inject_omission(self, text: str) -> tuple[str, Label | None]:
        """Delete a sentence or clause programmatically."""
        # Split by punctuation
        parts = re.split(r'([.!?\u0964\u0965,;]+)', text)
        if len(parts) >= 3:
            # Delete one clause/sentence
            idx_to_remove = self.rng.choice(range(0, len(parts) - 1, 2))
            deleted_part = parts[idx_to_remove]
            if len(deleted_part.strip()) > 3:
                before = "".join(parts[:idx_to_remove])
                after = "".join(parts[idx_to_remove + 2:])
                mutated = (before + after).strip()
                span_start = len(before)
                label = Label(
                    type=ErrorCategory.OMISSION,
                    severity=Severity.MAJOR,
                    span=(span_start, span_start + 10),
                    description=f"Injected omission of clause: '{deleted_part[:30]}...'"
                )
                return mutated, label

        # Fallback: drop the last 30% of words
        words = text.split()
        if len(words) > 5:
            keep_count = int(len(words) * 0.65)
            mutated = " ".join(words[:keep_count])
            label = Label(
                type=ErrorCategory.OMISSION,
                severity=Severity.MAJOR,
                span=(len(mutated), len(mutated) + 5),
                description="Injected omission of trailing text"
            )
            return mutated, label

        return text, None

    def inject_addition(self, text: str) -> tuple[str, Label | None]:
        """Duplicate a clause to create hallucination/addition."""
        words = text.split()
        if len(words) >= 4:
            slice_len = min(4, len(words) // 2)
            dup_words = " " + " ".join(words[:slice_len])
            insert_pos = len(text) // 2
            mutated = text[:insert_pos] + dup_words + text[insert_pos:]
            label = Label(
                type=ErrorCategory.ADDITION,
                severity=Severity.MAJOR,
                span=(insert_pos, insert_pos + len(dup_words)),
                description="Injected addition/duplication of phrase"
            )
            return mutated, label
        return text, None

    def inject_format_error(self, text: str) -> tuple[str, Label | None]:
        """Break Markdown syntax or LaTeX delimiters."""
        if "**" in text:
            idx = text.find("**")
            # Remove closing or opening **
            mutated = text[:idx] + text[idx + 2:]
            label = Label(
                type=ErrorCategory.FORMAT,
                severity=Severity.MINOR,
                span=(idx, idx + 2),
                description="Injected broken bold markdown '**'"
            )
            return mutated, label

        if "$" in text:
            idx = text.find("$")
            mutated = text[:idx] + text[idx + 1:]
            label = Label(
                type=ErrorCategory.FORMAT,
                severity=Severity.MAJOR,
                span=(idx, idx + 2),
                description="Injected unclosed LaTeX math '$'"
            )
            return mutated, label

        # If clean text, inject an unclosed markdown tag
        mutated = text + " **महत्वपूर्ण"
        pos = len(text) + 1
        label = Label(
            type=ErrorCategory.FORMAT,
            severity=Severity.MINOR,
            span=(pos, pos + 2),
            description="Injected unclosed markdown tag"
        )
        return mutated, label

    def inject_wrong_script(self, text: str, lang: str) -> tuple[str, Label | None]:
        """Inject characters from an inappropriate alphabet/script or untranslated Latin."""
        # Inject an untranslated English clause
        untranslated = " according to standard international scientific reports "
        insert_pos = len(text) // 2
        mutated = text[:insert_pos] + untranslated + text[insert_pos:]
        label = Label(
            type=ErrorCategory.WRONG_LANGUAGE,
            severity=Severity.CRITICAL,
            span=(insert_pos, insert_pos + len(untranslated)),
            description="Injected untranslated English clause into Indic translation"
        )
        return mutated, label

    def inject_speech_truncation(self, audio_bytes: bytes) -> tuple[bytes, Label | None]:
        """Truncate PCM WAV audio at 60% of length."""
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                params = wf.getparams()
                frames = wf.readframes(wf.getnframes())
            # Keep first 60%
            cutoff = int(len(frames) * 0.60)
            # Ensure alignment to 2-byte samples
            cutoff = cutoff - (cutoff % 2)
            out_buf = io.BytesIO()
            with wave.open(out_buf, "wb") as wf_out:
                wf_out.setparams(params)
                wf_out.writeframes(frames[:cutoff])
            label = Label(
                type=ErrorCategory.SPEECH_OMISSION,
                severity=Severity.CRITICAL,
                span=None,
                description="Injected audio truncation at 60% of duration"
            )
            return out_buf.getvalue(), label
        except Exception as e:
            logger.warning(f"Failed to inject speech truncation: {e}")
            return audio_bytes, None

    def inject_speech_silence(self, audio_bytes: bytes) -> tuple[bytes, Label | None]:
        """Insert a 2.5-second dead silence interval into the audio."""
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                framerate = wf.getframerate()
                channels = wf.getnchannels()
                params = wf.getparams()
                frames = wf.readframes(wf.getnframes())

            # 2.5s of silence in bytes
            silence_bytes = b'\x00' * int(framerate * 2.5 * channels * 2)
            midpoint = (len(frames) // 2) - ((len(frames) // 2) % 2)
            mutated_frames = frames[:midpoint] + silence_bytes + frames[midpoint:]

            out_buf = io.BytesIO()
            with wave.open(out_buf, "wb") as wf_out:
                wf_out.setparams(params)
                wf_out.writeframes(mutated_frames)

            label = Label(
                type=ErrorCategory.SPEECH_GARBLED,
                severity=Severity.MAJOR,
                span=None,
                description="Injected 2.5s unnatural silent stretch in middle of audio"
            )
            return out_buf.getvalue(), label
        except Exception as e:
            logger.warning(f"Failed to inject audio silence: {e}")
            return audio_bytes, None

    def inject_errors_into_items(
        self,
        clean_items: list[DatasetItem],
        error_rate: float = 0.50,
    ) -> list[DatasetItem]:
        """
        Produce benchmark dataset with ~50% clean items and ~50% injected errors.
        Guarantees ground-truth labels for precision/recall calibration.
        """
        output_items: list[DatasetItem] = []

        injection_methods = [
            ("number", self.inject_number_error),
            ("omission", self.inject_omission),
            ("addition", self.inject_addition),
            ("format", self.inject_format_error),
            ("wrong_script", self.inject_wrong_script),
        ]

        for item in clean_items:
            # Deep copy item
            item_copy = DatasetItem(**item.model_dump())

            # Decide whether to keep clean or inject error
            if self.rng.random() > error_rate or not item_copy.translation:
                output_items.append(item_copy)
                continue

            # Pick an injection mutation
            _, method = self.rng.choice(injection_methods)
            if method == self.inject_wrong_script:
                mutated_text, label = method(item_copy.translation, item_copy.lang)
            else:
                mutated_text, label = method(item_copy.translation)

            if label:
                item_copy.translation = mutated_text
                item_copy.labels.append(label)

            output_items.append(item_copy)

        return output_items
