#!/bin/bash
# One-time setup. Run it from the project folder with:   bash setup.sh
# It installs everything and asks for your keys (typing is hidden),
# then saves them into .env. Safe to run again to change keys.
set -e
cd "$(dirname "$0")"

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== 1/3  Installing system tools (ffmpeg, fonts) =="
$SUDO apt-get update -q
$SUDO apt-get install -y -q ffmpeg fonts-noto-core python3-venv python3-pip

echo "== 2/3  Installing Python packages =="
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

echo "== 3/3  Your settings =="
[ -f .env ] || cp .env.example .env
echo "Paste each value and press Enter. Keys are hidden while you paste."
echo "Press Enter without typing anything to keep the current value."
read -r -s -p "Gemini API key: " GEMINI_API_KEY; echo
read -r -s -p "DeepSeek API key: " DEEPSEEK_API_KEY; echo
read -r -s -p "Telegram bot token: " TELEGRAM_BOT_TOKEN; echo
read -r -p "Your Telegram user ID (number from @userinfobot): " TELEGRAM_ADMIN_ID
read -r -p "Your channel name (e.g. @asianproxy): " CHANNEL_NAME

export GEMINI_API_KEY DEEPSEEK_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_ADMIN_ID CHANNEL_NAME
./venv/bin/python - <<'EOF'
import os
names = ["GEMINI_API_KEY", "DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_ID", "CHANNEL_NAME"]
lines = open(".env", encoding="utf-8").read().splitlines()
for i, line in enumerate(lines):
    name = line.split("=", 1)[0].strip()
    value = os.environ.get(name, "").strip()
    if name in names and value:
        lines[i] = f"{name}={value}"
open(".env", "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
chmod 600 .env   # only you can read the keys

echo
echo "Saved. Check (keys shortened on purpose):"
grep -E "^(GEMINI_API_KEY|DEEPSEEK_API_KEY|TELEGRAM_BOT_TOKEN)=" .env | cut -c1-24
grep -E "^(TELEGRAM_ADMIN_ID|CHANNEL_NAME)=" .env
echo
echo "Done! Next time you log in, run:  cd ~/tiktok-maker && source venv/bin/activate"
