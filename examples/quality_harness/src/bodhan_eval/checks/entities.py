"""Named entity and technical term preservation check."""

from __future__ import annotations

import logging
import re
from typing import Any

from bodhan_eval.checks.base import BaseCheck
from bodhan_eval.types import CheckResult, DatasetItem, ErrorCategory, Severity

logger = logging.getLogger(__name__)

# Common stop words to exclude from entity candidate extraction
ENGLISH_STOP_WORDS = {
    "A", "An", "The", "And", "Or", "But", "If", "Then", "In", "On", "At", "To",
    "For", "With", "By", "From", "About", "As", "Into", "Like", "Through", "After",
    "Over", "Between", "Out", "Against", "During", "Without", "Before", "Under",
    "Around", "Among", "This", "That", "These", "Those", "It", "They", "We", "You",
    "He", "She", "His", "Her", "Their", "Our", "My", "Your", "Its", "Is", "Are", "Was", "Were"
}


class EntityCheck(BaseCheck):
    """
    Checks that proper nouns, acronyms, and technical terms in the source
    are preserved or correctly represented in the translated output.
    """

    name: str = "entity_preservation"
    description: str = "Checks preservation of named entities, proper nouns, and acronyms"
    requires_api: bool = False
    cost_tier: str = "free"

    def _extract_entities(self, text: str) -> list[str]:
        """Extract candidate proper nouns, quoted strings, and uppercase acronyms."""
        entities: list[str] = []

        # 1. Quoted terms: "..." or '...'
        quotes = re.findall(r'["\']([^"\']{2,40})["\']', text)
        entities.extend(quotes)

        # 2. Acronyms / Uppercase words (e.g. NASA, AI, UNESCO, ISRO)
        acronyms = re.findall(r'\b[A-Z]{2,10}\b', text)
        entities.extend(acronyms)

        # 3. Capitalized words not at sentence start
        words = text.split()
        for i, w in enumerate(words):
            clean = re.sub(r'[^\w]', '', w)
            if i > 0 and clean and clean[0].isupper() and clean not in ENGLISH_STOP_WORDS and len(clean) > 2:
                entities.append(clean)

        return list(dict.fromkeys(entities))  # Deduplicate preserving order

    async def run(
        self,
        item: DatasetItem,
        translation: str,
        lang: str,
        **context: Any,
    ) -> list[CheckResult]:
        if not translation:
            return []

        entities = self._extract_entities(item.source)
        if not entities:
            return []

        results: list[CheckResult] = []
        trans_lower = translation.lower()

        for ent in entities:
            ent_lower = ent.lower()
            # If the entity was in Latin script and appears directly in translation
            if ent_lower in trans_lower:
                continue

            # In Indian translations, English proper nouns are often phonetically transliterated.
            # We check if an entity is an acronym or distinctive keyword that was completely erased.
            if len(ent) >= 3 and ent.isupper():
                # E.g. "NASA" or "ISRO" - if not found in Latin or obvious representation
                if ent not in translation:
                    results.append(
                        CheckResult(
                            check_name=self.name,
                            passed=False,
                            error_type=ErrorCategory.ENTITY,
                            severity=Severity.MAJOR,
                            span=None,
                            evidence=f"Acronym/Entity '{ent}' from source is missing in translation.",
                            confidence=0.80,
                        )
                    )

        return results
