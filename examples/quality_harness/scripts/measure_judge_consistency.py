"""Measure uncached category agreement on a small, seeded sample of the demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
from time import monotonic

from bodhan_eval.api.llm import LLMJudgeClient
from bodhan_eval.concurrency import AsyncRateLimiter
from bodhan_eval.config import Config
from bodhan_eval.dataset import read_dataset
from bodhan_eval.judge.judge import JudgeOrchestrator
from bodhan_eval.types import ItemReport


async def measure(args):
    config = Config()
    if not config.llm_api_key:
        raise ValueError("The consistency check requires a configured LLM API key")
    client = LLMJudgeClient(
        config.llm_base_url, config.llm_model, config.llm_api_key, rate_limiter=AsyncRateLimiter(3),
    )
    judge = JudgeOrchestrator(client)
    dataset, _ = read_dataset(args.dataset)
    rows = []
    for raw in args.items.read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        row["flags"] = [
            {**flag, "error_type": flag["category"], "passed": False}
            for flag in row["flags"] if flag["check_name"] != "llm_judge"
        ]
        rows.append(ItemReport.model_validate(row))
    reports = {report.id: report for report in rows if report.translation}
    rng = random.Random(args.seed)
    selected = []
    for language in ("hi", "ta", "bn"):
        for seeded in (False, True):
            group = [item for item in dataset if item.lang == language and item.id in reports and bool(item.labels) == seeded]
            selected.extend(rng.sample(group, 3))

    async def check(item):
        report = reports[item.id]
        try:
            score = await judge.measure_consistency(
                item, report.translation, n_runs=2, prior_checks=report.flags,
            )
        except Exception as exc:
            return {"id": item.id, "language": item.lang, "agreement": None, "error": type(exc).__name__}
        return {"id": item.id, "language": item.lang, "agreement": score}

    start = monotonic()
    results = await asyncio.gather(*(check(item) for item in selected))
    matches = sum(row["agreement"] == 1 for row in results)
    return {
        "model": config.llm_model,
        "seed": args.seed,
        "items": len(results),
        "calls_per_item": 2,
        "identical_category_lists": matches,
        "unavailable": sum(row["agreement"] is None for row in results),
        "agreement_rate": round(matches / len(results), 4),
        "elapsed_seconds": round(monotonic() - start, 2),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/demo.jsonl"))
    parser.add_argument("--items", type=Path, default=Path("sample_report/items.jsonl"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = asyncio.run(measure(args))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['identical_category_lists']}/{result['items']} matching pairs. {result['unavailable']} unavailable.")


if __name__ == "__main__":
    main()
