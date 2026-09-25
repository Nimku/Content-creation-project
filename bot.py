"""The Telegram bot: the part you talk to.

Send it a screen recording with a short note as the caption, for example:
    how to add a proxy in Telegram
It then, one clip at a time:
  1. asks Gemini what happens in the clip (once per clip)
  2. asks DeepSeek for a script per language
  3. makes the voice with edge-tts
  4. builds the video
  5. sends you each video as a file with Approve / Regenerate / Skip buttons

Normally it runs as a background service (see README). To run it by hand instead:
    nice -n 15 ionice -c3 python3 bot.py        (Ctrl+C to stop)
"""
import json
import logging
import queue
import threading
import time
import traceback
from pathlib import Path

import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from analyze import analyze
from edit import render
from housekeeping import cleanup, log_event, total_cost
from script import LANGUAGE_NAMES, write_script
from voice import make_voice

config.require("TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_ID")
ADMIN_ID = int(config.TELEGRAM_ADMIN_ID)
MAX_DOWNLOAD_MB = 20  # Telegram does not let bots download bigger files
MAX_UPLOAD_MB = 49    # ...or upload bigger ones

config.LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_DIR / "bot.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("bot")

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
# Work waiting to be done, one at a time: ("new", clip path, note) or ("regen", clip name, language)
jobs = queue.Queue()


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
    text = raw.strip().splitlines()[0] if raw.strip() else type(e).__name__
    return text[:300]


# ---------------- receiving clips ----------------
@bot.message_handler(commands=["start", "help"])
def on_start(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.reply_to(message, "Send me a screen recording (under 20 MB) with a short note as the caption, "
                          "for example: how to add a proxy in Telegram\n\n/cost shows the total AI cost so far.")


@bot.message_handler(commands=["cost"])
def on_cost(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, f"Estimated AI cost so far: ${total_cost():.4f} (details in logs/videos.csv)")


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

    jobs.put(("new", path, note))
    waiting = jobs.qsize() - 1
    bot.reply_to(message, "Got it! Working on it now..." if waiting <= 0
                 else f"Got it! {waiting} other job(s) are ahead in the queue.")
    if not note:
        tell_admin("Tip: next time add a short note as the caption, e.g. 'how to add a proxy in Telegram'.")


# ---------------- making videos ----------------
def buttons(clip, lang):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("✅ Approve", callback_data=f"ok|{clip}|{lang}"),
           InlineKeyboardButton("🔄 Regenerate", callback_data=f"re|{clip}|{lang}"),
           InlineKeyboardButton("⏭ Skip", callback_data=f"skip|{clip}|{lang}"))
    return kb


def make_video(analysis, lang, fresh_script=False):
    """Script -> voice -> video -> send to Telegram, for one language. Returns the DeepSeek cost."""
    clip = Path(analysis["video"]).stem
    script = write_script(analysis, lang, fresh=fresh_script)
    voice = make_voice(clip, script)
    out = config.OUTPUT_DIR / f"{clip}_{lang}.mp4"
    started = time.time()
    render(analysis, script, voice, out)
    log.info("Rendered %s in %.0fs", out.name, time.time() - started)

    size_mb = out.stat().st_size / 1024 / 1024
    if size_mb > MAX_UPLOAD_MB:
        raise RuntimeError(f"The {lang} video is {size_mb:.0f} MB, too big for Telegram (max 50 MB).")
    caption = f'[{LANGUAGE_NAMES.get(lang, lang)}]\n\n{script["caption"]}\n\n{" ".join(script["hashtags"])}'
    with open(out, "rb") as f:
        bot.send_document(ADMIN_ID, f, caption=caption[:1024], reply_markup=buttons(clip, lang), timeout=300)
    log_event(clip, lang, "made", script["deepseek_cost_usd"])
    return script["deepseek_cost_usd"]


def new_clip(path, note):
    analysis = analyze(path, note)
    clip = path.stem
    log_event(clip, "all", "analyzed (Gemini)", analysis["gemini_cost_usd"])
    langs = ", ".join(LANGUAGE_NAMES.get(x, x) for x in config.LANGUAGES)
    tell_admin(f'Gemini found {len(analysis["steps"])} steps. Now making {len(config.LANGUAGES)} videos '
               f'({langs}). This takes a few minutes...')
    cost = analysis["gemini_cost_usd"]
    for lang in config.LANGUAGES:
        try:
            cost += make_video(analysis, lang)
        except Exception as e:  # one language failing should not stop the others
            log.error("Failed on %s %s:\n%s", clip, lang, traceback.format_exc())
            tell_admin(f"Sorry, the {LANGUAGE_NAMES.get(lang, lang)} video failed:\n{plain_error(e)}")
    tell_admin(f"All done! Estimated AI cost for this clip: ${cost:.4f}")


def regenerate(clip, lang):
    steps_file = config.WORK_DIR / clip / "steps.json"
    if not steps_file.exists():
        tell_admin("That clip is too old (its files were cleaned up). Please send the video again.")
        return
    make_video(json.loads(steps_file.read_text(encoding="utf-8")), lang, fresh_script=True)


def worker():
    cleanup()
    while True:
        try:
            job = jobs.get(timeout=3600)
        except queue.Empty:
            removed = cleanup()  # nothing to do for an hour: tidy up old files
            if removed:
                log.info("Cleanup removed %d old items", removed)
            continue
        try:
            if job[0] == "new":
                new_clip(job[1], job[2])
            else:
                regenerate(job[1], job[2])
        except Exception as e:
            log.error("Job %s failed:\n%s", job, traceback.format_exc())
            tell_admin(f"Sorry, something went wrong:\n{plain_error(e)}")
        finally:
            jobs.task_done()


# ---------------- the Approve / Regenerate / Skip buttons ----------------
@bot.callback_query_handler(func=lambda call: True)
def on_button(call):
    if call.from_user.id != ADMIN_ID:
        return
    action, clip, lang = call.data.split("|")
    name = LANGUAGE_NAMES.get(lang, lang)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass  # buttons already removed

    if action == "ok":
        bot.answer_callback_query(call.id, "Approved!")
        log_event(clip, lang, "approved")
        script_file = config.WORK_DIR / clip / f"script_{lang}.json"
        tell_admin(f"✅ {name} approved. Save the video above and upload it to TikTok. "
                   "Long-press the next message to copy the caption:")
        if script_file.exists():
            s = json.loads(script_file.read_text(encoding="utf-8"))
            tell_admin(f'{s["caption"]}\n\n{" ".join(s["hashtags"])}')
    elif action == "re":
        bot.answer_callback_query(call.id, "Making a new version...")
        log_event(clip, lang, "regenerate")
        jobs.put(("regen", clip, lang))
        tell_admin(f"🔄 Making a new {name} version (new script and voice)...")
    elif action == "skip":
        bot.answer_callback_query(call.id, "Skipped")
        log_event(clip, lang, "skipped")
        (config.OUTPUT_DIR / f"{clip}_{lang}.mp4").unlink(missing_ok=True)
        tell_admin(f"⏭ {name} skipped.")


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    log.info("Bot started. Send it a video on Telegram.")
    tell_admin("Bot started. Send me a screen recording with a short note as the caption.")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
