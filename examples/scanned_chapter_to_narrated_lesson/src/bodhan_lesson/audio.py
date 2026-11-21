"""Speak short chunks, verify them with Bodhan ASR and master chapter MP3s."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import html
import json
import re
import subprocess
import unicodedata
import wave

from rapidfuzz.distance import Levenshtein

from .core import StageError, atomic, context, json_file, public_error


def wav_info(data):
    try:
        with wave.open(BytesIO(data), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
                raise StageError("Indic-Speak audio was not 24 kHz mono PCM16")
            frames = wav.getnframes()
            raw = wav.readframes(frames)
        if len(raw) != frames * 2 or not frames:
            raise StageError("Indic-Speak WAV data was incomplete")
        if not any(raw):
            raise StageError("Indic-Speak returned silent WAV data")
        return frames / 24000, raw
    except (EOFError, wave.Error) as exc:
        raise StageError("Indic-Speak returned invalid WAV data") from exc


def speak_wav(data):
    """Normalize the hosted WAV/MP3 response before sending it back to ASR."""
    if data.startswith(b"RIFF"):
        try:
            wav_info(data)
            return data
        except StageError:
            pass
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-ac", "1", "-ar", "24000", "-f", "s16le", "pipe:1"],
        input=data, capture_output=True, timeout=45,
    )
    if result.returncode or not result.stdout:
        raise StageError("Indic-Speak audio could not be decoded")
    buf = BytesIO()
    with wave.open(buf, "wb") as output:
        output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        output.writeframes(result.stdout)
    return buf.getvalue()


def ff(*args, program="ffmpeg"):
    try:
        base = [program, "-hide_banner", "-nostdin", "-y"] if program == "ffmpeg" else [program]
        r = subprocess.run([*base, *map(str, args)], capture_output=True, check=True, timeout=160)
        return r.stdout, r.stderr.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        raise StageError(f"{program} could not process audio") from exc


def normalize_text(text):
    out = []
    for ch in unicodedata.normalize("NFKC", text).casefold():
        try:
            out.append(str(unicodedata.decimal(ch)))
        except ValueError:
            if ch.isalpha() or unicodedata.category(ch).startswith("M"):
                out.append(ch)
            elif ch.isspace():
                out.append(" ")
    return " ".join("".join(out).split())


def cer(expected, actual):
    ref, hyp = (normalize_text(x).replace(" ", "") for x in (expected, actual))
    return Levenshtein.distance(ref, hyp), max(1, len(ref))


def repeated_phrase(reference, hypothesis):
    def ngrams(text):
        words = normalize_text(text).split()
        return [tuple(words[i:i+3]) for i in range(len(words)-2)]
    ref, hyp = ngrams(reference), ngrams(hypothesis)
    return any(hyp.count(seq) >= max(3, ref.count(seq) + 2) for seq in set(hyp))


def speech_chunks(text, limit=210):
    text = " ".join(text.split())
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?।॥؟。])\s+", text)
    out, pending, count = [], "", 0
    for piece in sentences:
        if len(piece) > limit:
            if pending:
                out.append(pending)
                pending, count = "", 0
            words = piece.split()
            for word in words:
                if len(word) > limit:
                    raise StageError("narration contains an unsplittable word")
                if pending and len(pending) + len(word) + 1 > limit:
                    out.append(pending)
                    pending = ""
                pending = (pending + " " + word).strip()
            if pending:
                out.append(pending)
                pending = ""
            continue
        if pending and (len(pending) + len(piece) + 1 > limit or count == 2):
            out.append(pending)
            pending, count = "", 0
        pending = (pending + " " + piece).strip()
        count += 1
    return out + ([pending] if pending else [])


def verified_clip(svc, input_text, language, voice, style, ctx, attempts, depth=0):
    best = None
    retry_limit = 2 if depth == 0 else 1
    for attempt in range(1, retry_limit + 1):
        info = {"text": input_text, "attempt": attempt, "split_depth": depth}
        attempts.append(info)
        try:
            audio = speak_wav(svc.speak(input_text, language, voice, ctx, style,
                                       "" if attempt == 1 else f"qa-retry-{attempt}"))
            seconds, raw = wav_info(audio)
            info["duration_s"] = round(seconds, 3)
            if seconds > 29.5:
                info["status"] = "longer_than_asr_limit"
                break
            if seconds < 0.2:
                raise StageError("synthesis audio was too short")
            asr = svc.transcribe(audio, language, seconds, ctx)
            errors, count = cer(input_text, asr)
            ref = normalize_text(input_text).replace(" ", "")
            hyp = normalize_text(asr).replace(" ", "")
            length_ratio = len(hyp) / max(1, len(ref))
            repeated = repeated_phrase(input_text, asr)
            rate = errors / count
            failure = repeated or (len(ref) >= 12 and not 0.47 <= length_ratio <= 1.8) or not hyp
            info.update(cer=round(rate, 4), transcript=asr, repetition=repeated, length_ratio=round(length_ratio, 3),
                        status="accepted" if rate <= 0.26 and not failure else "qa_rejected")
            clip = (raw, {"text": input_text, "transcript": asr, "duration_s": seconds,
                          "cer": rate, "err": errors, "len": count,
                          "qa": "pass" if info["status"] == "accepted" else "review"})
            if info["status"] == "accepted":
                return [clip]
            if not failure and rate <= 0.48 and (best is None or rate < best[1]["cer"]):
                best = clip
        except StageError as exc:
            info.update(status="failed", reason=public_error(exc))
            if "key" in str(exc) or "(401)" in str(exc) or "(403)" in str(exc) or "budget" in str(exc):
                raise
    if depth < 2 and len(input_text) >= 38:
        splits = [m.start() for m in re.finditer(r"\s+", input_text)]
        if splits:
            i = min(splits, key=lambda x: abs(x - len(input_text) / 2))
            if i >= 8 and len(input_text) - i > 8:
                recovered = []
                try:
                    for fragment in (input_text[:i], input_text[i:].strip()):
                        recovered.extend(verified_clip(svc, fragment, language, voice, style, ctx, attempts, depth + 1))
                    if best is None or sum(c["err"] for _, c in recovered) / sum(c["len"] for _, c in recovered) <= best[1]["cer"]:
                        return recovered
                except StageError:
                    if best is None:
                        raise
    if best is not None:
        return [best]
    raise StageError("narration did not pass Bodhan back-transcription after retries")


def write_wav(path, pcm_iter, gap_ms=0):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        gap = b"\x00\x00" * (24 * gap_ms)
        for i, raw in enumerate(pcm_iter):
            if i and gap:
                stream.writeframesraw(gap)
            stream.writeframesraw(raw)


def extract_stats(stdout):
    hits = list(re.finditer(r'\{\s*"input_i"\s*:.*?\}', stdout, re.S))
    return json.loads(hits[-1].group()) if hits else {}


def loudness(path):
    _, stderr = ff("-nostats", "-i", path, "-af", "loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json",
                   "-f", "null", "-")
    return float(extract_stats(stderr)["input_i"])


def normal_wav(source, target):
    base = "loudnorm=I=-16:TP=-1.5:LRA=9"
    _, stderr = ff("-nostats", "-i", source, "-af", base + ":print_format=json", "-f", "null", "-")
    stats = extract_stats(stderr)
    if stats and all(re.fullmatch(r"-?\d+(?:\.\d+)?", str(stats.get(k, ""))) for k in (
        "input_i", "input_lra", "input_tp", "input_thresh", "target_offset"
    )):
        base += (f":measured_I={stats['input_i']}:measured_LRA={stats['input_lra']}"
                 f":measured_TP={stats['input_tp']}:measured_thresh={stats['input_thresh']}"
                 f":offset={stats['target_offset']}:linear=true")
    ff("-loglevel", "error", "-i", source, "-af", base, "-ar", "24000", "-ac", "1",
       "-c:a", "pcm_s16le", target)


def join_short_prose(items, limit=210):
    """Keep complete adjacent prose together within one verified speech request."""
    grouped = []
    for item in items:
        previous = grouped[-1] if grouped else None
        if (previous and previous["policy"] == item["policy"] == "read_prose"
                and previous["text"].endswith((".", "!", "?", "।", "॥", "؟"))
                and len(previous["text"]) + len(item["text"]) + 1 <= limit):
            grouped[-1] = {
                "text": previous["text"] + " " + item["text"],
                "source_blocks": previous["source_blocks"] + item["source_blocks"],
                "policy": item["policy"],
            }
        else:
            grouped.append(item)
    return grouped


def synth_section(svc, items, language, voice, style, section, file, wav_file):
    attempts, included, failed, raw_frames = [], [], [], []
    text_offset = 0.0
    for item in join_short_prose(items):
        for number, text in enumerate(speech_chunks(item["text"]), 1):
            ctx = context("audio_verify", language=language, section=section,
                          blocks=item["source_blocks"], chunk=number)
            history = []
            try:
                accepted = verified_clip(svc, text, language, voice, style, ctx, history)
                for raw, stats in accepted:
                    begin = text_offset + (0.12 if raw_frames else 0)
                    text_offset = begin + stats["duration_s"]
                    included.append({**stats, "start_s": round(begin, 3), "end_s": round(text_offset, 3),
                                     "source_blocks": item["source_blocks"], "policy": item["policy"]})
                    raw_frames.append(raw)
            except StageError as exc:
                failed.append({"source_blocks": item["source_blocks"], "reason": public_error(exc), "text": text})
                if "budget" in str(exc) or "(401)" in str(exc) or "(403)" in str(exc):
                    attempts.extend({**h, "source_blocks": item["source_blocks"]} for h in history)
                    return dict(status="failed", fatal=public_error(exc), accepted_chunks=included,
                                attempts=attempts, failed_chunks=failed, file=None, cer=None, duration_s=None)
            attempts.extend({**h, "source_blocks": item["source_blocks"]} for h in history)
    if not raw_frames:
        return dict(status="failed", accepted_chunks=included, attempts=attempts, failed_chunks=failed,
                    file=None, cer=None, duration_s=None)
    file.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=wav_file.parent) as work:
        source = Path(work) / "raw.wav"
        write_wav(source, raw_frames, gap_ms=120)
        normal_wav(source, wav_file)
        mp3 = Path(work) / "verified.mp3"
        ff("-loglevel", "error", "-i", wav_file, "-codec:a", "libmp3lame", "-b:a", "64k",
           "-metadata", "comment=AI-generated narration", mp3)
        observed = loudness(mp3)
        atomic(file, mp3.read_bytes())
    n = sum(x["len"] for x in included)
    return dict(status="partial" if failed else "ok", accepted_chunks=included, attempts=attempts,
                failed_chunks=failed, file=file.name, duration_s=round(text_offset, 3),
                cer=round(sum(x["err"] for x in included) / n, 4), lufs=observed,
                lufs_on_target=abs(observed + 16) <= 1,
                cer_scope="accepted_chunks_only" if failed else "all_chunks")


def _meta_text(s):
    return re.sub(r"[\r\n]+", " ", str(s)).translate(str.maketrans({x: "\\" + x for x in "\\;#="}))


def chapter_track(entries, language, out, work):
    if not entries:
        return None
    joined, meta = work / "lesson.wav", work / "chapters.txt"
    start_frame = 0
    metadata = [";FFMETADATA1", "title=" + _meta_text(f"Narrated lesson ({language})"), "comment=AI-generated narration"]
    markers = []
    with wave.open(str(joined), "wb") as result:
        result.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        for i, (wav, title, index) in enumerate(entries):
            if i:
                result.writeframesraw(b"\x00\x00" * 9600)
                start_frame += 9600
            with wave.open(str(wav), "rb") as stream:
                frames = stream.getnframes()
                result.writeframesraw(stream.readframes(frames))
            end = start_frame + frames
            metadata.extend(("[CHAPTER]", "TIMEBASE=1/24000", f"START={start_frame}", f"END={end}", "title=" + _meta_text(title)))
            markers.append({"section": index, "title": title, "start_s": round(start_frame / 24000, 3),
                            "end_s": round(end / 24000, 3)})
            start_frame = end
    meta.write_text("\n".join(metadata) + "\n", encoding="utf-8")
    staged = work / "lesson.mp3"
    ff("-loglevel", "error", "-i", joined, "-i", meta, "-map_metadata", "1", "-map_chapters", "1",
       "-id3v2_version", "3", "-codec:a", "libmp3lame", "-b:a", "64k", staged)
    raw, _ = ff("-v", "error", "-show_chapters", "-of", "json", staged, program="ffprobe")
    chapters = json.loads(raw).get("chapters", [])
    if len(chapters) != len(markers):
        raise StageError("MP3 section markers could not be verified")
    atomic(out / f"lesson.{language}.mp3", staged.read_bytes())
    json_file(out / f"chapters.{language}.json", markers)
    observed = loudness(staged)
    return {"sections": len(markers), "duration_s": markers[-1]["end_s"], "embedded_markers": len(chapters),
            "lufs": observed, "lufs_on_target": abs(observed + 16) <= 1}


def slug(text, fallback):
    asciified = unicodedata.normalize("NFKD", html.unescape(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", asciified.lower()).strip("-")[:54].rstrip("-") or f"section-{fallback}"
