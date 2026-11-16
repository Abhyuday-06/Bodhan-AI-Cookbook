"""Public command-line interface."""
from __future__ import annotations

import argparse
from pathlib import Path
import logging
import sys

from dotenv import load_dotenv

from .pipeline import execute


def bounded(minimum, maximum):
    def parse(raw):
        try:
            value = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("expected an integer") from exc
        if not minimum <= value <= maximum:
            raise argparse.ArgumentTypeError(f"expected a value from {minimum} through {maximum}")
        return value
    return parse


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Turn scanned pages into a translated, AI-narrated lesson.")
    p.add_argument("--input", type=Path, required=True, help="scanned PDF or directory of PNG/JPG pages")
    p.add_argument("--langs", required=True, help="comma-separated target codes, e.g. hi,ta,bn")
    p.add_argument("--out", type=Path, required=True, help="output folder; reuse for a cached rerun")
    p.add_argument("--source-lang", help="override OCR-text language detection")
    p.add_argument("--glossary", type=Path, help="optional YAML term-to-language mapping")
    p.add_argument("--voices", type=Path, help="optional YAML language-to-voice mapping")
    p.add_argument("--code-mixed", action="store_true", help="Bodhan code-mixed narration, native Markdown")
    p.add_argument("--jobs", type=bounded(1, 16), default=8, help="max simultaneous API requests (default: 8)")
    p.add_argument("--dpi", type=bounded(100, 350), default=205, help="PDF rasterization DPI (default: 205)")
    p.add_argument("--ocr-repair-limit", type=bounded(0, 12), default=4, help="max block crops per page (default: 4)")
    p.add_argument("--no-cache", action="store_true", help="do not read or write the local response cache")
    p.add_argument("--max-inr", type=float, help="optional estimated Bodhan spend cap, excluding LLM costs")
    return p.parse_args(argv)


def main(argv=None):
    if hasattr(sys.stderr, "reconfigure"):
        # Ensure machine-readable logs do not depend on a Windows console code page.
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(Path.cwd() / ".env", override=False)
    return execute(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
