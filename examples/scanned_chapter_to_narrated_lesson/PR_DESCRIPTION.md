# [Agentic Eng Assignment] Narrated lesson — Abhyuday Vaish

## Summary

Adds one self-contained CLI that turns textbook scans into structured, translated Markdown and AI-generated narration. It repairs layout, preserves protected content through translation, and uses Bodhan ASR to catch and retry speech omissions and repetitions.

## How to run

From a clean clone with Python 3.10+, Poppler and FFmpeg available:

```bash
cd examples/scanned_chapter_to_narrated_lesson
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -e .
cp .env.example .env
# Set the four Bodhan keys and the LLM endpoint, model and key in .env.
python -m bodhan_lesson --input path/to/scans --langs hi,ta,bn --out ./out
```

## Architecture

See the [component diagram](DESIGN.md#architecture): rasterize → OCR and recovery → layout and assembly → translation and narration planning → TTS and back-transcription → mastering and report.

## Workflow

See the [workflow diagram](DESIGN.md#workflow-and-recovery) for the OCR, translation and speech checks, retry paths and partial output behavior.

## Where the LLM is used, and why

The LLM decides difficult block order, source labels for shared scripts, exact English glossary candidates, and English readings for complex material. See [the decision table](DESIGN.md#where-the-llm-decides) for the deterministic fallback and guardrails at each stage.

## How tables, equations and figures are narrated

A table row can be read as “For the north pool, the morning value is 12 and the evening value is 19.” `$x+4=9$` is read as “x plus 4 equals 9.” A figure is explained from its caption and matching text, such as a transversal crossing two parallel lines.

## Bodhan models used

Hosted Indic-OCR with HTML tables, Indic-Translate including the explicit English pivot and optional code-mixed narration, Indic-Speak with native voice defaults, and Indic-Transcribe on short chunks.

## Results

Pending hosted NCERT Hindi/Tamil/Bengali and Malayalam-source runs. Add live output links, structure and coverage results, CER and loudness from the final reports here before opening the PR.

## Demo video

Pending the ≤5-minute recording of the full run and its outputs.

## Trade-offs and known limitations

Numeric and structural invariants are exact; translation semantics and OCR recall still require reference or native review. The pipeline keeps merged-cell HTML and keeps unverified OCR out of narration. It uses captions and explicit text for figures and flags figures when the evidence is insufficient.

## Cost and runtime

Pending measured wall time and estimated INR per page and language from a cold hosted run. Estimates use the posted Bodhan rates; LLM cost is separate.

## AI assistance

Codex assisted with implementation, tests, documentation and local verification.
