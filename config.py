"""Loads every setting from the .env file, so the rest of the code can just do:
    import config
    config.GEMINI_MODEL
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def get(name, default=""):
    return os.getenv(name, default).strip()


# Folders
INPUT_DIR = BASE_DIR / "data" / "input"
WORK_DIR = BASE_DIR / "data" / "work"
OUTPUT_DIR = BASE_DIR / "data" / "output"
LOG_DIR = BASE_DIR / "logs"
FONT_DIR = BASE_DIR / "fonts"

# API keys
GEMINI_API_KEY = get("GEMINI_API_KEY")
DEEPSEEK_API_KEY = get("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = get("TELEGRAM_ADMIN_ID")

# Models
GEMINI_MODEL = get("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL = get("GEMINI_FALLBACK_MODEL", "gemini-3.7-flash")
GEMINI_FPS = float(get("GEMINI_FPS", "2"))
DEEPSEEK_MODEL = get("DEEPSEEK_MODEL", "deepseek-chat")

# Prices (USD per 1 million tokens)
GEMINI_PRICE_INPUT = float(get("GEMINI_PRICE_INPUT", "0.75"))
GEMINI_PRICE_OUTPUT = float(get("GEMINI_PRICE_OUTPUT", "3.75"))
DEEPSEEK_PRICE_INPUT = float(get("DEEPSEEK_PRICE_INPUT", "0.28"))
DEEPSEEK_PRICE_OUTPUT = float(get("DEEPSEEK_PRICE_OUTPUT", "0.42"))

# Channel and languages
CHANNEL_NAME = get("CHANNEL_NAME", "@YourChannel")
LANGUAGES = [x.strip() for x in get("LANGUAGES", "en,id,vi,th,ms").split(",") if x.strip()]

# Look
ARROW_COLOR = get("ARROW_COLOR", "#FF3B30")
SUBTITLE_COLOR = get("SUBTITLE_COLOR", "#FFFFFF")
HIGHLIGHT_COLOR = get("HIGHLIGHT_COLOR", "#FFD60A")
STEP_LABEL_COLOR = get("STEP_LABEL_COLOR", "#0A84FF")

ZOOM = float(get("ZOOM", "1.35"))
VOICE_RATE = get("VOICE_RATE", "+10%")
RENDER_THREADS = int(get("RENDER_THREADS", "2"))

CLEANUP_DAYS = float(get("CLEANUP_DAYS", "3"))


def voice_for(lang):
    """Voice name for a language code, e.g. voice_for("th") -> VOICE_TH from .env"""
    return get("VOICE_" + lang.upper())


def require(*names):
    """Stop with a clear message if a needed setting is empty."""
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit("Missing setting(s) in .env: " + ", ".join(missing))
