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

The hosted runs processed both textbook chapters. The table shows verified translated blocks and sections with accepted audio. The final speech passes used `--brief-narration`, which selects a short translated statement per section and leaves the translated Markdown and unavailable-block markers in the output. The validation report separates intentional narration omissions from unavailable translations.

| Chapter | Target | Run status | Verified blocks | Sections with audio | New attributed cost |
| --- | --- | --- | ---: | ---: | ---: |
| NCERT Lines and Angles | Hindi | partial | 272 / 273 | 13 / 14 | ₹0.0427 |
| NCERT Lines and Angles | Tamil | partial | 272 / 273 | 11 / 14 | ₹0.3258 |
| NCERT Lines and Angles | Bengali | partial | 271 / 273 | 13 / 14 | ₹0.0987 |
| SCERT Kerala Equations | Hindi | partial | 181 / 186 | 7 / 7 | ₹0.2456 |

The first NCERT section contains a document identifier and is skipped for speech. Tamil sections 7 and 11 failed back-transcription and have no audio. All four assembled tracks passed the −16 LUFS ±1 target.

- NCERT Lines and Angles (en) processed 20 of 20 pages. The continuation took 238.44 seconds and added ₹0.4672 (₹0.0234 per input page).
- SCERT Kerala Equations (ml) processed 12 of 12 pages. The continuation took 56.67 seconds and added ₹0.2456 (₹0.0205 per input page).
- Before the recovery pass, the recorded NCERT continuation took 9079.51 seconds and added ₹3.6713. Provider rate limits and retries contributed to its runtime.

The figures reflect reused provider caches and exclude Gemini charges. Shared calls such as OCR contribute to the chapter totals. See the [validation report](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/narrated-lesson-takehome-demo/narrated-lesson-validation.json) for measured CER, loudness and costs.

## Demo video

The walkthrough replays the recorded chapter runs and plays excerpts from the AI-generated narration. [Demo walkthrough](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/narrated-lesson-takehome-demo/narrated-lesson-demo.mp4)

The output archive contains a short verified audio sample per chapter and target language. [Audio samples and validation metrics](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/narrated-lesson-takehome-demo/narrated-lesson-outputs.zip)

## Trade-offs and known limitations

Numeric and structural invariants are exact; translation semantics and OCR recall still require reference or native review. The pipeline keeps merged-cell HTML and keeps unverified OCR out of narration. It uses captions and explicit text for figures and flags figures when the evidence is insufficient.

## Cost and runtime

- NCERT Lines and Angles (en) processed 20 of 20 pages. The continuation took 238.44 seconds and added ₹0.4672 (₹0.0234 per input page).
- SCERT Kerala Equations (ml) processed 12 of 12 pages. The continuation took 56.67 seconds and added ₹0.2456 (₹0.0205 per input page).
- Before the recovery pass, the recorded NCERT continuation took 9079.51 seconds and added ₹3.6713. Provider rate limits and retries contributed to its runtime.

The continuation figures reflect successful cached work and new Bodhan requests. The separate OCR cache warm-up for the Malayalam chapter used an estimated ₹2.40. Gemini usage is outside the Bodhan INR totals.

## AI assistance

Codex assisted with implementation, tests, documentation and local verification.
