# Quality Harness submission draft

**PR title** `[Agentic Eng Assignment] Quality harness — Abhyuday Vaish`

## Summary

Audits Indian-language translation and speech for defects, reports evidence at span level, and calibrates on labelled examples. The CLI supports an output-generation mode and can compare two reports for regressions.

## How to run

Install Python 3.10 or newer and FFmpeg. From the Cookbook root:

```bash
cd examples/quality_harness
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -e .
cp .env.example .env
# Configure the Bodhan keys and an OpenAI-compatible judge.
python -m bodhan_eval --dataset data/demo.jsonl --langs hi,ta,bn \
  --out outputs/eval --calibration data/calibration_labels.jsonl --concurrency 1
```

## Architecture

Free checks inspect script, numerals, reference similarity and markup. Back-translation and selective speech recognition add evidence before the judge. See the [architecture diagram](README.md#architecture-overview).

## Harness design

The [execution flow](README.md#execution-flow--cost-gating) shows which checks run, when speech applies, and how evidence becomes item findings. The [design notes](README.md#how-it-works) cover scoring, normalization and calibration.

## Where the LLM is used, and why

The judge examines existing translations, back-translations and deterministic findings and returns structured categories, spans and explanations. The demo used Gemini 3.1 Flash-Lite on Vertex AI. Calibration compares flagged spans and categories with the labelled set. The cached rerun produced identical item records. In a separate check, all 18 pairs of uncached requests agreed on the category list. [Consistency report](sample_report/judge-consistency.json)

## Bodhan models used

Hosted Indic-Translate performed back-translation on the full dataset. For the three speech examples, Indic-Translate generated translations, Indic-Speak synthesized their audio, and Indic-Transcribe supplied the verification transcripts.

## Results

The 120-item live benchmark completed every check. Seeded defect recall was 96.5%, localization overlap 79.3%, category accuracy 96.5% and clean-item false alarms 0%. Span and category calibration measured 43.8% precision and 60.2% F1. The per-language and per-category results are in the [sample report](sample_report/summary.md).

## Demo video

The 1:25 replay shows the benchmark invocation, its report, the cached comparison and the speech samples. [Public walkthrough](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/quality-harness-takehome-demo/quality-harness-demo.mp4)

## Trade-offs and known limitations

Several seeded items produced extra or overlapping flags, which lowered span-level precision. The main dataset measures translation quality. The separate three-item speech check verifies the live audio path. The consistency result covers an 18-item sample. Performance on a fresh 200-item audio run remains unmeasured.

## Cost and runtime

The paced 120-item run used ₹0.0333 in new Bodhan calls and took 938.9 seconds. Its continuation recovered two throttled checks in 6.6 seconds at ₹0.0005. Across those two passes this was about 788 seconds and ₹0.028 per 100 items on a partially populated cache. The subsequent repeat took 0.3 seconds at ₹0.00. The separate three-item speech run took 24.3 seconds at ₹0.0913 in new Bodhan usage. Its sample size and cache differ from the translation benchmark. Gemini charges are outside these figures.

## AI assistance

Codex assisted with provider compatibility, validation, tests, report documentation and the walkthrough.
