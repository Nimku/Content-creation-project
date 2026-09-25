"""STEP 2 - UNDERSTAND
Sends a screen recording to Gemini and gets back a list of steps:
when each step starts and ends, what happens, and where the finger tapped.

Try it by itself:
    python3 analyze.py data/input/myclip.mp4 "how to add a proxy in Telegram"

The result is saved as data/work/<clip name>/steps.json.
If that file already exists, Gemini is NOT called again (saves money):
every language reuses the same steps. Add --fresh to force a new analysis.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import config

PROMPT = """You are watching a phone screen recording for a short tutorial video.
"Show taps" is turned on, so a small white/grey dot appears wherever the finger touches the screen.
The creator's note about this clip: "{note}"
The video is {duration:.1f} seconds long.

Split the recording into the separate steps the user performs (usually 2 to 8 steps).
For each step give:
- "start": second when the step begins (number, e.g. 3.5)
- "end": second when the step ends (number, bigger than start, at most {duration:.1f})
- "action": one short plain sentence describing what happens, e.g. "Tap Settings in the menu"
- "target": the name of the button or item that was tapped (or "" if none)
- "tap_x": horizontal position of the tap dot as a fraction of screen width (0 = left edge, 1 = right edge), or null if there is no tap in this step
- "tap_y": vertical position of the tap dot as a fraction of screen height (0 = top, 1 = bottom), or null if there is no tap

Steps must be in time order and must not overlap.
Reply with ONLY this JSON, nothing else:
{{"steps": [{{"start": 0.0, "end": 2.5, "action": "...", "target": "...", "tap_x": 0.5, "tap_y": 0.3}}]}}"""


def video_duration(path):
    """Length of the video in seconds (uses ffprobe, which comes with ffmpeg)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def to_seconds(value):
    """Accepts 12, 12.5, "12.5", "0:12" or "00:00:12" and returns seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ":" in text:
        seconds = 0.0
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
        return seconds
    return float(text)


def to_fraction(value):
    """Tap position as 0..1. Gemini sometimes answers on a 0..1000 or 0..100 scale; fix that."""
    if value is None or value == "":
        return None
    v = float(value)
    if v > 100:
        v = v / 1000
    elif v > 1:
        v = v / 100
    return min(max(v, 0.0), 1.0)


def check_steps(text, duration):
    """Turns Gemini's reply into a clean list of steps.
    Raises ValueError with a plain explanation if the reply is broken."""
    # Remove ```json fences if Gemini added them
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"reply is not valid JSON ({e})")

    raw_steps = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError('reply has no "steps" list')

    steps = []
    for i, s in enumerate(raw_steps, 1):
        if not isinstance(s, dict):
            raise ValueError(f"step {i} is not an object")
        try:
            start = to_seconds(s["start"])
            end = to_seconds(s["end"])
            tap_x = to_fraction(s.get("tap_x"))
            tap_y = to_fraction(s.get("tap_y"))
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"step {i} has a missing or bad value ({e})")
        action = str(s.get("action", "")).strip()
        if not action:
            raise ValueError(f"step {i} has no action text")
        start = max(0.0, start)
        end = min(end, duration)
        if end <= start:
            raise ValueError(f"step {i} ends before it starts ({start} -> {end})")
        if (tap_x is None) != (tap_y is None):
            tap_x = tap_y = None  # half a position is useless
        steps.append({
            "start": round(start, 2), "end": round(end, 2), "action": action,
            "target": str(s.get("target") or "").strip(),
            "tap_x": tap_x, "tap_y": tap_y,
        })

    steps.sort(key=lambda s: s["start"])
    # Fix small overlaps: a step ends where the next one begins
    for a, b in zip(steps, steps[1:]):
        if a["end"] > b["start"]:
            a["end"] = b["start"]
        if a["end"] <= a["start"]:
            raise ValueError(f'two steps start at the same time ({a["start"]}s)')
    return steps


def upload_video(client, path):
    """Uploads the clip to Gemini and waits until Gemini has processed it."""
    f = client.files.upload(file=str(path))
    for _ in range(60):  # wait at most ~2 minutes
        state = str(getattr(f.state, "name", f.state))
        if state == "ACTIVE":
            return f
        if state == "FAILED":
            raise RuntimeError("Gemini could not process the video file")
        time.sleep(2)
        f = client.files.get(name=f.name)
    raise RuntimeError("Gemini took too long to process the video")


def ask_gemini(video_path, note, duration):
    """Calls Gemini (with one retry if the answer is broken).
    Returns (steps, cost_in_usd)."""
    from google import genai
    from google.genai import types

    config.require("GEMINI_API_KEY")
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    uploaded = upload_video(client, video_path)

    video_part = types.Part(
        file_data=types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
        video_metadata=types.VideoMetadata(fps=config.GEMINI_FPS),
    )
    prompt = PROMPT.format(note=note, duration=duration)
    cost = 0.0
    last_error = None
    try:
        for attempt in (1, 2):
            text_prompt = prompt
            if last_error:
                text_prompt += f"\n\nYour previous answer was rejected because: {last_error}. Please fix it."
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[video_part, text_prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            cost += gemini_cost(response)
            try:
                return check_steps(response.text or "", duration), cost
            except ValueError as e:
                last_error = str(e)
                print(f"Attempt {attempt}: Gemini's answer was broken ({e})"
                      + (", trying once more..." if attempt == 1 else ""))
    finally:
        try:
            client.files.delete(name=uploaded.name)  # don't leave the clip on Google's servers
        except Exception:
            pass
    raise RuntimeError(f"Gemini gave a broken answer twice: {last_error}")


def gemini_cost(response):
    """Estimated cost of one Gemini call in US dollars, from the token counts."""
    u = response.usage_metadata
    if not u:
        return 0.0
    tokens_in = u.prompt_token_count or 0
    tokens_out = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    return (tokens_in * config.GEMINI_PRICE_INPUT + tokens_out * config.GEMINI_PRICE_OUTPUT) / 1_000_000


def analyze(video_path, note, fresh=False):
    """Main function. Returns a dict with the steps, saved to steps.json."""
    video_path = Path(video_path)
    work = config.WORK_DIR / video_path.stem
    work.mkdir(parents=True, exist_ok=True)
    result_file = work / "steps.json"

    if result_file.exists() and not fresh:
        print(f"Using saved analysis: {result_file}")
        result = json.loads(result_file.read_text(encoding="utf-8"))
        result["gemini_cost_usd"] = 0.0  # nothing was spent this time
        return result

    duration = video_duration(video_path)
    print(f"Sending {video_path.name} ({duration:.1f}s) to {config.GEMINI_MODEL}...")
    steps, cost = ask_gemini(video_path, note, duration)
    result = {"video": str(video_path), "note": note, "duration": duration,
              "steps": steps, "gemini_cost_usd": round(cost, 5)}
    result_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def print_steps(result):
    print(f'\nFound {len(result["steps"])} steps in {result["duration"]:.1f}s of video:\n')
    for i, s in enumerate(result["steps"], 1):
        tap = (f'tap at x={s["tap_x"]:.2f}, y={s["tap_y"]:.2f}'
               if s["tap_x"] is not None else "no tap")
        print(f'  Step {i}: {s["start"]:5.1f}s - {s["end"]:5.1f}s  {s["action"]}  ({tap})')
    print(f'\nEstimated Gemini cost: ${result["gemini_cost_usd"]:.4f}')


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--fresh"]
    if not args:
        print('Usage: python3 analyze.py <video.mp4> "short note" [--fresh]')
        sys.exit(1)
    note = args[1] if len(args) > 1 else ""
    print_steps(analyze(args[0], note, fresh="--fresh" in sys.argv))
