# Video Dubbing Pipeline

Dub an English video into any of Indic-Speak's 13 production languages. The pipeline writes an AI-dubbed MP4, SRT subtitles, an English transcript, and measurements for each spoken segment.

## Setup

Install Python 3.10+ and FFmpeg with `ffmpeg` and `ffprobe` on PATH. Then run from a clean Cookbook clone:

```bash
cd examples/video_dubbing
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -e .
cp .env.example .env
```

On PowerShell, use `.\.venv\Scripts\Activate.ps1` and `Copy-Item .env.example .env`. Fill the three scoped Bodhan keys and the OpenAI-compatible `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY`. Only the LLM sees English transcripts for glossary planning and condensation. It never gets media or writes target-language text.

Alternatively, build and run the container from the recipe directory:

```bash
docker build -t bodhan-dub .
docker run --rm --env-file .env -v "$PWD:/work" bodhan-dub \
  --input inputs/video.mp4 --langs hi,ta,bn --out outputs/demo
```

## Run

```bash
python -m bodhan_dub --input inputs/video.mp4 --langs hi,ta,bn --out outputs/demo
```

Inputs can be 1–15 minute MP4, MOV, MKV, or WebM. Languages are `en,hi,bn,mr,te,ta,gu,kn,ml,or,pa,as,ur`. Use `--code-mixed` to ask Indic-Translate for code-mixed output. Use `--glossary glossary.yaml` for exact source terms and approved translations, and `--voices voices.yaml` to choose the fixed voice per language. For example:

```yaml
# glossary.yaml
cosine: {hi: "कोसाइन", ta: "கோசைன்", bn: "কোসাইন"}
AB: {all: AB}
```

```yaml
# voices.yaml
hi: Kavya
ta: {voice: Anitha}
bn: Ishita
```

`--jobs` limits concurrent provider calls. `--max-cost-inr` sets an optional estimated Bodhan spend cap. Set `BODHAN_REQUEST_INTERVAL_S` to space hosted requests per Bodhan model. A transient rate limit backs off and enables per-model spacing. Credit exhaustion pauses new requests to the affected model for the rest of the run, while cached results remain available. Reuse the same output directory for a cached rerun, or use `--no-cache` to measure a cold run. Use `--allow-short-input` for smoke tests under one minute.

```text
outputs/demo/
  transcript.en.json
  report.json
  hi/
    video.hi.mp4
    subtitles.hi.srt
    segments.hi.json
  ta/
  bn/
```

A segment that cannot pass verification keeps the corresponding original sound and records the reason. A failed language does not block the others, and an incomplete run exits nonzero. Use the paths in the current report to identify the files produced by a rerun.

## How it works

1. Decode audio with FFmpeg and detect speech windows with WebRTC VAD. Prefer quiet boundaries and keep each source transcription request well below 30 seconds. Indic-Transcribe returns text, so timestamps refer to the audio windows.
2. Select recurring names and acronyms from the English transcript. Translate only with Indic-Translate. Validate target script, numerals and glossary terms. Retry with exact markers when the first pass changes protected text.
3. Synthesize with Indic-Speak. If the clip is too long for its slot, ask the LLM to condense the **English** side, then translate and synthesize again. Remove exterior silence and cap tempo changes at 1.2×.
4. Back-transcribe the retimed audio with Indic-Transcribe. Record character error rate (CER), extra repetitions and possible omissions. Retry a bad clip without dropping other languages.
5. Place accepted speech on the original timeline, master the voice to −16 LUFS where headroom allows, and keep background audio outside replaced slots. Embed subtitles and label the output as AI-dubbed.

See the [architecture and decision notes](DESIGN.md) for the control flow, request and cost accounting, and quality thresholds.

## Demo and outputs

Use the English **Class 9 Mathematics, Chapter 6, Period 1** video from the supplied assignment brief. Save the official signed download as `inputs/class9-math.mp4` and request `hi,ta,bn`. Source files and generated media remain out of Git.

The full hosted run used the 329.27-second Class 9 source. It processed 38 source speech windows and reported `partial`. Windows without a verified dub retain the original audio. FFprobe checked the language-tagged audio and subtitle streams and the output durations.

| Language | Run status | Verified windows | Median CER | Speech LUFS | Duration difference |
| --- | --- | ---: | ---: | ---: | ---: |
| Hindi | partial | 31 of 38 | 0.1333 | -15.95 | 0.0 ms |
| Tamil | partial | 30 of 38 | 0.1118 | -15.96 | 0.0 ms |
| Bengali | partial | 27 of 38 | 0.1385 | -16.04 | 0.0 ms |

The funded continuation took 1523.06 seconds and added ₹5.91912. The final pass took 265.12 seconds and added ₹0.00000 in Bodhan usage. Those figures reflect a populated cache and exclude Gemini charges. The public metrics report lists each category of skipped window. [Validation metrics](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/video-dubbing-takehome-demo/video-dubbing-validation.json)

The walkthrough replays the full-input run with shortened pauses, reports coverage and plays verified audio excerpts. [Demo walkthrough](https://github.com/Abhyuday-06/Bodhan-AI-Cookbook/releases/download/video-dubbing-takehome-demo/video-dubbing-demo.mp4)

## Verification

```bash
python -m pip install -e ".[test]"
python -m pytest -q
python -m ruff check src tests
```

The 30-second smoke test uses synthetic audio and mocked model responses, with an actual FFmpeg mux and FFprobe verification. It exercises the public command path, subtitles, timing, the live API response shapes, failure isolation and zero-call resume. The live run measures duration and loudness separately.

## Limitations

- Window timestamps approximate utterance boundaries. Adjacent fast speakers and continuous speech can share a window. There is no speaker diarization or voice cloning.
- Center-panned source dialogue is reduced during replaced spans. The stereo side component remains. Mono music or music mixed in the center with speech cannot be recovered reliably.
- CER and script checks measure agreement and coverage. Human listeners are still needed to assess meaning, voice quality and timing at a mouth movement level.
- Automatic terminology planning preserves exact English names and acronyms. Supply a glossary when a consistent target-language equivalent matters.
- Peak headroom takes priority when −16 LUFS would clip. The report exposes measurable misses, incomplete segments and spend estimates.
- On-screen translation and a separate UI are outside the CLI recipe's scope.

Codex helped with implementation, tests and documentation. The workflow and provider calls are inspectable in the segment and run reports.
