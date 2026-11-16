# Scanned Chapter to Narrated Lesson

> Turn a textbook chapter into a structured lesson and AI-generated narration that students can follow without seeing the page.

**Bodhan models:** Indic-OCR, Indic-Translate, Indic-Speak and Indic-Transcribe

**Format:** Python CLI

**Targets:** English (`en`), Hindi (`hi`), Bengali (`bn`), Marathi (`mr`), Telugu (`te`), Tamil (`ta`), Gujarati (`gu`), Kannada (`kn`), Malayalam (`ml`), Odia (`or`), Punjabi (`pa`), Assamese (`as`), Urdu (`ur`)

## Setup

Use Python 3.10 or newer, Poppler (`pdfinfo`, `pdftoppm`), and FFmpeg (`ffmpeg`, `ffprobe`, `libmp3lame`). For example, on Ubuntu install `poppler-utils ffmpeg python3-venv`; on macOS use `brew install poppler ffmpeg`; on Windows install Poppler and FFmpeg and add their binaries to PATH. The optional demo helper also uses Poppler's `pdfseparate` and `pdfunite`. The Docker build installs Poppler and FFmpeg.

From a clean Cookbook clone:

```bash
cd examples/scanned_chapter_to_narrated_lesson
python -m venv .venv
source .venv/bin/activate                   # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -e .
cp .env.example .env                       # PowerShell: Copy-Item .env.example .env
```

Fill in the four model keys in `.env` (or inject them into the environment). Set `LLM_BASE_URL` to the provider's OpenAI-compatible API base, usually ending in `/v1`, `LLM_MODEL` to its model ID, and `LLM_API_KEY` to its credential. The LLM is used for judgment and selected English narration; missing or failing LLM calls fall back where possible. Environment variables override `.env`. Run from the recipe directory if using the file.

Container alternative:

```bash
docker build -t bodhan-lesson .
docker run --rm --env-file .env -v "$PWD:/work" bodhan-lesson \
  --input /work/inputs/chapter.pdf --langs hi,ta,bn --out /work/out
```

## Run

```bash
python -m bodhan_lesson --input path/to/scans/ --langs hi,ta,bn --out ./out
```

Use a scanned PDF or a flat directory of 5–30 PNG/JPG images. Images sort naturally (`page2` before `page10`). Each PDF page is rasterized by Poppler; the pipeline never requests or reads the document text layer. Smaller inputs are accepted for smoke tests. If the language is ambiguous, use `--source-lang`, e.g. `--source-lang mr`. There is one global API concurrency cap (`--jobs 8` by default), an optional estimated Bodhan spending cap (`--max-inr`), and `--no-cache` for a cold run. Use a dedicated output directory per chapter. A rerun refreshes the report and files that can be regenerated; use the new report's file entries to identify current outputs if a rerun is partial.

`--voices voices.yaml` selects a fixed Indic-Speak voice or voice and style:

```yaml
hi: {voice: Kavya, style: educational lecture}
ta: Anitha
bn: Ishita
```

`--glossary glossary.yaml` maps a source term to approved forms in other languages. For Indic source chapters, the `en` entry serves as the pivot term. Use plain terms and avoid variant inflections in the mapping. Automatically suggested entries appear in `source/glossary.json` and apply only when a validated translation is available.

```yaml
corresponding angles:
  hi: संगत कोण
  ta: ஒத்த கோணங்கள்
  bn: অনুরূপ কোণ
```

`--code-mixed` requests Bodhan's code-mixed mode for narration while Markdown stays native. This can add latency and uses the narrated script, including retained English terms, as the ASR reference.

## How it works

1. **Scan:** render each page, call Indic-OCR, record raw layout blocks, and optionally re-OCR a contrast-enhanced page or cropped block. Reorder supported columns and let the LLM judge difficult layouts using block IDs and geometry.
2. **Assemble:** filter running furniture, join likely continuation text and tables, separate margin notes and unresolved OCR, and assign section and block provenance.
3. **Translate:** call Indic-Translate on short units, protect Markdown syntax, numbers, units, and LaTeX, and retry failed structural spans as separate text fragments. For Indic-to-Indic translation, cache and reuse the English pivot.
4. **Plan speech:** read prose and lists in order. Verbalize math, describe tables by their headers and rows, and explain captioned diagrams using available OCR evidence. Only Indic-Translate supplies generated Indian-language script text.
5. **Verify speech:** use Indic-Speak for short chunks, transcribe each with Indic-Transcribe, and retry or split repetitions and omissions. Master sections at −16 LUFS and embed chapters in the full MP3.

See the [architecture and workflow diagrams](DESIGN.md#architecture), [decision and QA notes](DESIGN.md#where-the-llm-decides), and [submission draft](PR_DESCRIPTION.md).

### Outputs and partial runs

```text
out/
  report.json
  source/
    lesson.src.md
    pages/001.json
    figures/
    provenance.json
    glossary.json
    doubtful.json                 # when OCR needs review
    annotations.json              # when a margin note is found
  hi/
    lesson.hi.md
    narration_script.hi.json
    narration/01-*.hi.mp3
    lesson.hi.mp3                  # ID3 chapter markers
    chapters.hi.json
  ta/ ...
```

A failed page or language does not prevent other pages and languages from finishing. Exit code `1` means the run failed or has incomplete artifacts; read `report.json`. Each section records the source block IDs, Markdown line spans, language and structure checks, narration coverage, selected ASR, CER, retries and measured loudness. Doubtful text is excluded from translation and speech. Cached responses may contain source text and audio; treat the output and cache as local data. Every narration is AI-generated; MP3 metadata and JSON indicate this.

### Demonstrations

The `scripts/prepare_demo.py` helper downloads the [required NCERT Lines and Angles chapter](https://www.aspirationsinstitute.com/wp-content/uploads/2021/01/9-Maths-NCERT-Book-Lines-and-Angles.pdf) and extracts pages 33–44 (Chapter 2, *Equations*) from [SCERT Kerala Class 8 Mathematics, Malayalam medium](https://scert.kerala.gov.in/wp-content/uploads/2018/04/8_m_maths_part1.pdf). It keeps both PDFs in ignored `inputs/`. The first chapter exercises geometric notation and repeated footers; the second exercises Malayalam source detection, the English pivot, sidebars, math and tables.

```bash
python scripts/prepare_demo.py
python -m bodhan_lesson --input inputs/lines-and-angles.pdf --langs hi,ta,bn --out outputs/ncert
python -m bodhan_lesson --input inputs/equations-ml.pdf --langs hi --out outputs/scert
```

**Live demo outputs and video:** pending the hosted run. The [demo checklist](DEMO.md) records the artifacts and checks to capture. Textbook PDFs and generated textbook content are not included in this recipe.

### Tests

```bash
python -m pip install -r requirements.txt -e '.[test]'
python -m pytest -q
python -m ruff check src tests
```

The two-page smoke test uses simulated HTTP responses, synthetic image pages, and real FFmpeg MP3 processing. It checks the documented wire format, natural page order, cross-page assembly, exact protected spans, embedded chapter markers, failure isolation, and zero-cost resume. Separate tests cover column order and speech regeneration. The test data do not measure model quality.

## Limitations

- OCR confidence is for layout detection. A sharp-looking block can still be misrecognized; a doubtful block is quarantined when bounded repair cannot confirm it. The report cannot measure structure recall without a reference.
- Complex cross-page tables may remain in separate blocks when there is insufficient evidence of continuation. Very degraded or rotated phone photos can require rescanning.
- The Markdown check can verify exact structure, units, and notation, but not semantic equivalence. Target-script and coverage checks catch some failures. Glossary substitution prioritizes consistency and may need native review for grammatical agreement.
- Figures use OCR captions and corroborating nearby text. If neither is useful, narration points to the figure and reports the gap. Naïve symbol reading is avoided where a complex formula cannot be verbalized safely.
- CER measures agreement between two models, so ASR mistakes and verbalized digits can raise it even when speech is clear. Severe omissions/repetitions are rejected after bounded retries. ASR-based checks do not replace native listening.
- Cost is an estimate using the [Bodhan API pricing](https://console.bodhan.ai/), and excludes LLM spending and potentially billed rejected calls. Runtime depends on provider latency, quota, retry rates, input size, and cache use.

AI assistance: Codex helped implement the pipeline, write offline tests and documentation, and run local validation.
