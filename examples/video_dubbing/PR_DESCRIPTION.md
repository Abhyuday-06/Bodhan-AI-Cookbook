# [Agentic Eng Assignment] Video dubbing — Abhyuday Vaish

## Summary

Add a CLI for AI dubbing English videos with Indic-Transcribe, Indic-Translate, and Indic-Speak. It verifies retimed speech, preserves source video and usable background audio, and records incomplete segments.

## How to run

Follow the [recipe setup](README.md#setup) from a clean clone and run:

```bash
python -m bodhan_dub --input inputs/class9-math.mp4 --langs hi,ta,bn --out outputs/demo
```

## Architecture and workflow

See the [architecture diagram, decision flow and fallbacks](DESIGN.md). Speech detection and timing are deterministic. The LLM selects terms from the English transcript and proposes a shorter English paraphrase when the translation does not fit. The translated text always comes from Indic-Translate.

## Bodhan models used

Hosted Indic-Transcribe for detection-window text and back-transcription, Indic-Translate for the selected script, and Indic-Speak for the fixed target voice.

## Results

Add the measured demo coverage, sync offset, duration, CER and loudness from the cold hosted run and link the permitted output samples.

## Demo video

Add the walkthrough link after recording the full demo and playback.

## Trade-offs and known limitations

Speech-window timings approximate utterances since the hosted recognizer returns text. This recipe uses one selected voice per target, keeps available stereo side information, and preserves original speech when verification fails.

## Cost and runtime

Use measured per-language and per-input-minute costs from the demo report. The report separates cache hits from hosted calls.

## AI assistance

Codex assisted with implementation, tests, provider compatibility, and documentation.
