"""STEP 4 - VOICE
Turns a script into narration with edge-tts (free Microsoft voices).
Each part (hook, one line per step, call to action) becomes its own audio file,
together with the time of every spoken word (used for word-by-word subtitles).

Try it by itself (after script.py):
    python3 voice.py data/input/clip.mp4 en
"""
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import edge_tts

import config

# Emojis and symbols sound strange when read aloud, so they are removed
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def clean_for_speech(text):
    return re.sub(r"\s+", " ", EMOJI.sub("", text)).strip()


def audio_length(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


async def _speak(text, voice, mp3_path):
    """Saves the audio and returns the list of words with their start/end times (seconds)."""
    words = []
    tts = edge_tts.Communicate(text, voice, rate=config.VOICE_RATE, boundary="WordBoundary")
    with open(mp3_path, "wb") as f:
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000  # edge-tts counts in 100-nanosecond units
                words.append({"text": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 10_000_000})
    return words


def even_words(text, duration, lang):
    """Backup when the voice service gives no word times: spread the words evenly."""
    parts = text.split() if lang != "th" else [text[i:i + 8] for i in range(0, len(text), 8)]
    step = duration / max(len(parts), 1)
    return [{"text": p, "start": i * step, "end": (i + 1) * step} for i, p in enumerate(parts)]


def speak(text, lang, mp3_path):
    """Makes one audio file (3 tries, the free service sometimes hiccups).
    Returns {"file", "duration", "words"}."""
    voice = config.voice_for(lang)
    if not voice:
        raise RuntimeError(f"No voice set for language '{lang}'. Add VOICE_{lang.upper()}=... to .env")
    for attempt in range(3):
        try:
            words = asyncio.run(_speak(text, voice, mp3_path))
            if Path(mp3_path).stat().st_size > 0:
                break
        except Exception as e:
            print(f"Voice service problem ({e}), trying again...")
        time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError("The free voice service (edge-tts) did not answer. Try again in a few minutes.")
    duration = audio_length(mp3_path)
    if not words:
        words = even_words(text, duration, lang)
    return {"file": str(mp3_path), "duration": duration, "words": words}


def make_voice(clip_stem, script):
    """Makes narration for every part of the script.
    Returns {"hook": part, "lines": [part or None per step], "cta": part} and saves voice_<lang>.json."""
    lang = script["lang"]
    folder = config.WORK_DIR / clip_stem / f"voice_{lang}"
    folder.mkdir(parents=True, exist_ok=True)

    def part(text, name):
        text = clean_for_speech(text)
        return speak(text, lang, folder / f"{name}.mp3") if text else None

    voice = {
        "lang": lang,
        "hook": part(script["hook"], "hook"),
        "lines": [part(line, f"step{i}") for i, line in enumerate(script["lines"], 1)],
        "cta": part(script["cta"], "cta"),
    }
    (config.WORK_DIR / clip_stem / f"voice_{lang}.json").write_text(
        json.dumps(voice, indent=2, ensure_ascii=False), encoding="utf-8")
    return voice


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 voice.py <video.mp4> <language code, e.g. en>")
        sys.exit(1)
    stem, lang = Path(sys.argv[1]).stem, sys.argv[2]
    script_file = config.WORK_DIR / stem / f"script_{lang}.json"
    if not script_file.exists():
        sys.exit(f"No script yet. First run: python3 script.py {sys.argv[1]}")
    v = make_voice(stem, json.loads(script_file.read_text(encoding="utf-8")))
    parts = [v["hook"], *v["lines"], v["cta"]]
    total = sum(p["duration"] for p in parts if p)
    print(f"Made {sum(1 for p in parts if p)} audio parts, {total:.1f}s of speech, in {config.WORK_DIR / stem}")
