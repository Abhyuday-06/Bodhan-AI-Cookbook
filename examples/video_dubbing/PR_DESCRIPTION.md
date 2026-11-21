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

The [full-input validation results](README.md#demo-and-outputs) record Hindi, Tamil and Bengali coverage, CER and loudness. The measured output duration matched the 329-second source in all three languages. Remaining windows retain the source audio. The run was partial after the hosted Indic-Speak budget was exhausted.

## Demo video

The complete dubbing walkthrough is pending restored Indic-Speak capacity.

## Trade-offs and known limitations

Speech-window timings approximate utterances since the hosted recognizer returns text. This recipe uses one selected voice per target, keeps available stereo side information, and preserves original speech when verification fails.

## Cost and runtime

The cached full-input continuation took 528.03 seconds and added ₹0.05326 in Bodhan usage, which is about ₹0.0097 per minute of source video. These figures exclude cached work and Gemini charges. The run report records exact spend estimates per language.

## AI assistance

Codex assisted with implementation, tests, provider compatibility, and documentation.
