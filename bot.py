"""The Telegram bot.

Send it a screen recording with a short note as the caption, for example:
    how to add a proxy in Telegram
It saves the clip to data/input and works on it in the background.

Right now it runs STEP 1 (Gemini) and STEP 2 (DeepSeek scripts) and replies with the results.
Later steps (script, voice, video, approval buttons) get added here as they are built.

Start it (low priority, so your proxies stay fast):
    nice -n 15 ionice -c3 python3 bot.py
Stop it: Ctrl+C
"""
import logging
import queue
import threading
import time
import traceback

import telebot

import config
from analyze import analyze
from script import script_as_text, write_script

config.require("TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_ID")
ADMIN_ID = int(config.TELEGRAM_ADMIN_ID)
MAX_DOWNLOAD_MB = 20  # Telegram does not let bots download bigger files

config.LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_DIR / "bot.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("bot")

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
jobs = queue.Queue()  # clips waiting to be processed, handled one at a time


def tell_admin(text):
    try:
        bot.send_message(ADMIN_ID, text)
    except Exception:
        log.exception("Could not send a Telegram message")


def plain_error(e):
    """A short, readable error message instead of a wall of code."""
    raw = str(e)
    if "RESOURCE_EXHAUSTED" in raw or "429" in raw.split(".")[0]:
        return "Gemini's usage limit was reached. Wait a while, or add billing in Google AI Studio."
    if "API key not valid" in raw or "UNAUTHENTICATED" in raw or "PERMISSION_DENIED" in raw:
        return "Gemini refused the API key. Run 'bash setup.sh' and paste a working key."
    text = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return text[:300]


@bot.message_handler(commands=["start", "help"])
def on_start(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.reply_to(message, "Send me a screen recording (under 20 MB) with a short note as the caption, "
                          "for example: how to add a proxy in Telegram")


@bot.message_handler(content_types=["video", "document"])
def on_video(message):
    if message.from_user.id != ADMIN_ID:
        return  # ignore strangers
    media = message.video or message.document
    if message.document and not (media.mime_type or "").startswith("video/"):
        bot.reply_to(message, "That is not a video file. Please send a screen recording.")
        return
    if (media.file_size or 0) > MAX_DOWNLOAD_MB * 1024 * 1024:
        bot.reply_to(message, f"This video is {media.file_size / 1024 / 1024:.0f} MB. Telegram only lets bots "
                              f"download up to {MAX_DOWNLOAD_MB} MB. Please send a shorter clip, or send it as a "
                              "normal video (not as a file) so Telegram compresses it.")
        return

    note = (message.caption or "").strip()
    try:
        data = bot.download_file(bot.get_file(media.file_id).file_path)
    except Exception as e:
        bot.reply_to(message, "I could not download the video: " + plain_error(e))
        return
    path = config.INPUT_DIR / f"clip_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    path.write_bytes(data)
    log.info("Saved %s (%.1f MB), note: %s", path.name, len(data) / 1024 / 1024, note)

    jobs.put((path, note))
    waiting = jobs.qsize() - 1
    bot.reply_to(message, "Got it! Working on it now..." if waiting <= 0
                 else f"Got it! {waiting} other clip(s) are ahead in the queue.")
    if not note:
        tell_admin("Tip: next time add a short note as the caption, e.g. 'how to add a proxy in Telegram'.")


def process(path, note):
    """Everything that happens to one clip. More steps will be added here."""
    result = analyze(path, note)
    lines = [f'Gemini found {len(result["steps"])} steps:']
    for i, s in enumerate(result["steps"], 1):
        tap = f' (tap at {s["tap_x"]:.2f}, {s["tap_y"]:.2f})' if s["tap_x"] is not None else ""
        lines.append(f'{i}. {s["start"]:.1f}s-{s["end"]:.1f}s  {s["action"]}{tap}')
    tell_admin("\n".join(lines))

    cost = result["gemini_cost_usd"]
    for lang in config.LANGUAGES:
        script = write_script(result, lang)
        cost += script["deepseek_cost_usd"]
        tell_admin(script_as_text(script))
    tell_admin(f"Total AI cost for this clip: about ${cost:.4f}")


def worker():
    while True:
        path, note = jobs.get()
        try:
            process(path, note)
        except Exception as e:
            log.error("Failed on %s:\n%s", path.name, traceback.format_exc())
            tell_admin(f"Sorry, something went wrong with {path.name}:\n{plain_error(e)}")
        finally:
            jobs.task_done()


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    log.info("Bot started. Send it a video on Telegram. Press Ctrl+C to stop.")
    tell_admin("Bot started. Send me a screen recording with a short note as the caption.")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
