"""Configuration and settings for bodhan_eval."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file if present
load_dotenv()


@dataclass
class Config:
    """Runtime configuration for the evaluation harness."""
    # CLI options
    dataset: str = ""
    langs: str = "hi,ta,bn"
    out: str = "./report"
    generate: bool = False
    baseline: str | None = None
    calibration: str | None = None
    max_cost_inr: float = 50.0
    concurrency: int = 5
    cache_dir: str = ".bodhan_cache"
    log_level: str = "INFO"
    seed: int = 42

    # Bodhan API configuration
    bodhan_api_base: str = field(
        default_factory=lambda: os.environ.get("BODHAN_API_BASE", "https://api.bodhan.ai").rstrip("/")
    )
    bodhan_translate_key: str = field(
        default_factory=lambda: os.environ.get("BODHAN_TRANSLATE_KEY") or os.environ.get("BODHAN_API_KEY", "")
    )
    bodhan_speak_key: str = field(
        default_factory=lambda: os.environ.get("BODHAN_SPEAK_KEY") or os.environ.get("BODHAN_API_KEY", "")
    )
    bodhan_transcribe_key: str = field(
        default_factory=lambda: os.environ.get("BODHAN_TRANSCRIBE_KEY") or os.environ.get("BODHAN_API_KEY", "")
    )

    # LLM Judge configuration (OpenAI-compatible)
    llm_base_url: str = field(
        default_factory=lambda: os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    )
    llm_model: str = field(
        default_factory=lambda: os.environ.get("LLM_MODEL", "gpt-4o")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    )

    @property
    def target_langs(self) -> list[str]:
        """Parsed list of target language codes."""
        return [lang.strip() for lang in self.langs.split(",") if lang.strip()]

    def validate_api_access(self) -> dict[str, bool]:
        """Check which external capabilities have active credentials."""
        capabilities = {
            "translate": bool(self.bodhan_translate_key),
            "speak": bool(self.bodhan_speak_key),
            "transcribe": bool(self.bodhan_transcribe_key),
            "llm": bool(self.llm_api_key),
        }
        for cap, available in capabilities.items():
            if not available:
                logger.warning(
                    f"No credentials configured for {cap.upper()}. "
                    f"Associated model checks will be gracefully skipped or simulated."
                )
        return capabilities
