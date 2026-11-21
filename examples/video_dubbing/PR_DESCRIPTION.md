# [Agentic Eng Assignment] Video dubbing — Abhyuday Vaish

## Summary

Add a CLI for AI dubbing English videos with Indic-Transcribe, Indic-Translate, and Indic-Speak. It verifies retimed speech, preserves source video and usable background audio, and records incomplete segments.

## How to run

Follow the [recipe setup](README.md#setup) from a clean clone and run:

```bash
python -m bodhan_dub --input inputs/class9-math.mp4 --langs hi,ta,bn --out outputs/demo
```

## Architecture

FFmpeg and voice activity detection bound the recognition windows. The planner consumes the English text. The provider layer translates, synthesizes and verifies speech, then the muxer assembles accepted clips with the original picture and subtitles. [Architecture diagram](DESIGN.md#architecture)

## Workflow

The pipeline inventories the source, translates each speech window, fits and back-transcribes the dub, then packages verified clips and logs gaps. [Workflow and recovery](DESIGN.md#workflow)

## Where the LLM is used, and why

The LLM proposes protected names and shorter English phrasing for a tight timing slot. Glossary suggestions must occur in the source. A failed or invalid shortening keeps the existing wording, and an overlong clip is documented. Indic-Translate produces the target-language text. [Decisions and safeguards](DESIGN.md#decisions-and-safeguards)

## Bodhan models used

Hosted Indic-Transcribe for detection-window text and back-transcription, Indic-Translate for the selected script, and Indic-Speak for the fixed target voice.

## Results

The full hosted run used the 329.27-second Class 9 source. It processed 38 source speech windows and reported `partial`. Windows without a verified dub retain the original audio. FFprobe checked the language-tagged audio and subtitle streams and the output durations.

| Language | Run status | Verified windows | Median CER | Speech LUFS | Duration difference |
| --- | --- | ---: | ---: | ---: | ---: |
| Hindi | partial | 31 of 38 | 0.1333 | -15.95 | 0.0 ms |
| Tamil | partial | 30 of 38 | 0.1118 | -15.96 | 0.0 ms |
| Bengali | partial | 27 of 38 | 0.1385 | -16.04 | 0.0 ms |

The funded continuation took 1523.06 seconds and added ₹5.91912. The final pass took 265.12 seconds and added ₹0.00000 in Bodhan usage. Those figures reflect a populated cache and exclude Gemini charges. The public metrics report lists each category of skipped window. [Validation metrics](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/video-dubbing-takehome-demo/video-dubbing-validation.json)

## Demo video

The walkthrough replays the full-input run with shortened pauses, reports coverage and plays verified audio excerpts. [Demo walkthrough](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/video-dubbing-takehome-demo/video-dubbing-demo.mp4)

## Trade-offs and known limitations

Speech-window timings approximate utterances since the hosted recognizer returns text. This recipe uses one selected voice per target, keeps available stereo side information, and preserves original speech when verification fails.

## Cost and runtime

The funded continuation took 1523.06 seconds and added ₹5.91912. The final pass took 265.12 seconds and added ₹0.00000 in Bodhan usage. The live dubbing pass used about ₹1.0786 per source minute. Per source minute by language, Hindi ₹0.2632, Tamil ₹0.4401, Bengali ₹0.3753. Shared source-analysis costs are recorded separately.

## AI assistance

Codex assisted with implementation, tests, provider compatibility, and documentation.
