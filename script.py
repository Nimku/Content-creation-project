"""STEP 3 - SCRIPT
Uses the steps Gemini found to have DeepSeek write, for each language:
- a hook (first 2 seconds), one spoken line per step, and a call to action
- a TikTok caption and 3-5 hashtags

Try it by itself (after analyze.py has made steps.json):
    python3 script.py data/input/clip.mp4

Saved as data/work/<clip name>/script_<language>.json. Existing files are reused
(no cost). Add --fresh to write new ones.
"""
import json
import re
import sys
from pathlib import Path

import requests

import config

LANGUAGE_NAMES = {"en": "English", "id": "Indonesian", "vi": "Vietnamese", "th": "Thai", "ms": "Malay"}

PROMPT = """You write voice-overs for short, faceless TikTok tutorial videos (screen recordings of a phone).
The audience is Telegram users in Southeast Asia. Tone: friendly, simple, confident, like a helpful friend.

Topic of this video: "{note}"
The screen recording is {duration:.0f} seconds long. These are the steps shown, with the seconds available for each:
{steps}

Write everything in {language}. Use natural, everyday {language}, not a word-for-word translation.
Return JSON with exactly these keys:
- "hook": one very short, curiosity-grabbing sentence spoken in the first 2 seconds (max 8 words).
- "lines": a list with EXACTLY {count} strings, one spoken sentence per step, in the same order.
  Keep each line short enough to say in about the seconds available for that step.
  If a step repeats an earlier one, keep its line very short (e.g. "Same again." / "One more.").
- "cta": one short sentence asking viewers to join the Telegram channel {channel} for free proxies.
  Write {channel} exactly like that.
- "caption": a TikTok caption (1-2 short sentences, may include 1-2 emojis, mention {channel}).
- "hashtags": a list of 3 to 5 hashtags that fit {language}-speaking viewers, each starting with #.
The whole voice-over (hook + lines + cta) should take 20 to 45 seconds to say.
Reply with ONLY the JSON."""


def steps_text(steps, duration):
    rows = []
    for i, s in enumerate(steps):
        until = steps[i + 1]["start"] if i + 1 < len(steps) else duration
        rows.append(f'{i + 1}. {s["action"]}  (about {max(until - s["start"], 1):.0f}s)')
    return "\n".join(rows)


def check_script(text, count):
    """Checks DeepSeek's reply. Raises ValueError with a plain reason if it is broken."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"reply is not valid JSON ({e})")
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    for key in ("hook", "cta", "caption"):
        if not str(data.get(key, "")).strip():
            raise ValueError(f'"{key}" is missing')
    lines = data.get("lines")
    if not isinstance(lines, list) or len(lines) != count:
        raise ValueError(f'"lines" must have exactly {count} items')
    tags = data.get("hashtags")
    if isinstance(tags, str):
        tags = tags.split()
    if not isinstance(tags, list) or not tags:
        raise ValueError('"hashtags" is missing')
    tags = ["#" + str(t).strip().lstrip("#").replace(" ", "") for t in tags if str(t).strip().lstrip("#")][:5]
    if len(tags) < 3:
        raise ValueError("fewer than 3 hashtags")
    return {
        "hook": str(data["hook"]).strip(),
        "lines": [str(x).strip() for x in lines],
        "cta": str(data["cta"]).strip(),
        "caption": str(data["caption"]).strip(),
        "hashtags": tags,
    }


def ask_deepseek(prompt):
    """One DeepSeek call. Returns (reply text, cost in USD)."""
    config.require("DEEPSEEK_API_KEY")
    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
        json={
            "model": config.DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.9,
        },
        timeout=120,
    )
    if r.status_code == 401:
        raise RuntimeError("DeepSeek refused the API key. Run 'bash setup.sh' and paste a working key.")
    if r.status_code == 402:
        raise RuntimeError("DeepSeek balance is empty. Top up at platform.deepseek.com.")
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage") or {}
    cost = (usage.get("prompt_tokens", 0) * config.DEEPSEEK_PRICE_INPUT
            + usage.get("completion_tokens", 0) * config.DEEPSEEK_PRICE_OUTPUT) / 1_000_000
    return data["choices"][0]["message"]["content"], cost


def write_script(analysis, lang, fresh=False):
    """Makes (or reuses) the script for one language. Returns the script dict (with cost)."""
    work = config.WORK_DIR / Path(analysis["video"]).stem
    work.mkdir(parents=True, exist_ok=True)
    out_file = work / f"script_{lang}.json"
    if out_file.exists() and not fresh:
        script = json.loads(out_file.read_text(encoding="utf-8"))
        script["deepseek_cost_usd"] = 0.0
        return script

    steps = analysis["steps"]
    prompt = PROMPT.format(
        note=analysis.get("note") or "a Telegram tutorial", duration=analysis["duration"],
        steps=steps_text(steps, analysis["duration"]), count=len(steps),
        language=LANGUAGE_NAMES.get(lang, lang), channel=config.CHANNEL_NAME,
    )
    cost = 0.0
    last_error = None
    for attempt in (1, 2):
        text_prompt = prompt + (f"\n\nYour previous answer was rejected because: {last_error}. Fix it."
                                if last_error else "")
        reply, c = ask_deepseek(text_prompt)
        cost += c
        try:
            script = check_script(reply, len(steps))
            break
        except ValueError as e:
            last_error = str(e)
            print(f"[{lang}] DeepSeek's answer was broken ({e})" + (", trying once more..." if attempt == 1 else ""))
    else:
        raise RuntimeError(f"DeepSeek gave a broken {lang} script twice: {last_error}")

    script["lang"] = lang
    script["deepseek_cost_usd"] = round(cost, 5)
    out_file.write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    return script


def script_as_text(script):
    """Readable version, for printing or sending on Telegram."""
    lines = [f'[{LANGUAGE_NAMES.get(script["lang"], script["lang"])}]', f'Hook: {script["hook"]}']
    lines += [f"{i}. {line}" for i, line in enumerate(script["lines"], 1) if line]
    lines += [f'End: {script["cta"]}', "", f'Caption: {script["caption"]}', " ".join(script["hashtags"])]
    return "\n".join(lines)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--fresh"]
    if not args:
        print("Usage: python3 script.py <video.mp4> [--fresh]   (run analyze.py on it first)")
        sys.exit(1)
    steps_file = config.WORK_DIR / Path(args[0]).stem / "steps.json"
    if not steps_file.exists():
        sys.exit(f"No steps yet. First run: python3 analyze.py {args[0]}")
    analysis = json.loads(steps_file.read_text(encoding="utf-8"))
    total = 0.0
    for lang in config.LANGUAGES:
        s = write_script(analysis, lang, fresh="--fresh" in sys.argv)
        total += s["deepseek_cost_usd"]
        print(script_as_text(s), "\n")
    print(f"Estimated DeepSeek cost: ${total:.4f}")
