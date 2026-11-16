"""Command-line interface for bodhan_eval quality harness."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from bodhan_eval.config import Config
from bodhan_eval.orchestrator import Orchestrator


def setup_logging(log_level: str = "INFO", out_dir: Path | None = None) -> None:
    """Set up human-readable console logging and optional structured file logging."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        log_file = out_dir / "harness.log"
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser matching technical specifications."""
    parser = argparse.ArgumentParser(
        prog="bodhan_eval",
        description="Translation and speech quality evaluation harness for Bodhan AI Indic models.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Required arguments
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to evaluation JSONL dataset file.",
    )
    parser.add_argument(
        "--langs",
        required=True,
        help="Comma-separated target language codes (e.g., 'hi,ta,bn').",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Directory path where evaluation reports and logs will be written.",
    )

    # Optional flags
    parser.add_argument(
        "--generate",
        action="store_true",
        default=False,
        help="Synthesize missing translations (Indic-Translate) and speech (Indic-Speak) via Bodhan APIs.",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Path to previous evaluation report directory to produce diff.md regression analysis.",
    )
    parser.add_argument(
        "--calibration",
        default=None,
        help="Path to human-labelled JSONL dataset for threshold tuning and calibration metrics.",
    )
    parser.add_argument(
        "--max-cost-inr",
        type=float,
        default=50.0,
        help="Maximum expenditure cap in INR.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum concurrent asynchronous API requests.",
    )
    parser.add_argument(
        "--cache-dir",
        default=".bodhan_cache",
        help="Directory path for deterministic SHA-256 disk cache.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic sampling.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    out_path = Path(args.out).resolve()
    setup_logging(args.log_level, out_path)

    config = Config(
        dataset=args.dataset,
        langs=args.langs,
        out=args.out,
        generate=args.generate,
        baseline=args.baseline,
        calibration=args.calibration,
        max_cost_inr=args.max_cost_inr,
        concurrency=args.concurrency,
        cache_dir=args.cache_dir,
        log_level=args.log_level,
        seed=args.seed,
    )

    orchestrator = Orchestrator(config)
    try:
        asyncio.run(orchestrator.run())
        return 0
    except Exception as e:
        logging.getLogger(__name__).exception(f"Evaluation harness failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
