# TikTok Tutorial Maker

Send a phone screen recording to your Telegram bot. A few minutes later you get
finished vertical TikTok tutorials (AI voice, arrows, zoom, subtitles) in several
languages, each with Approve / Regenerate / Skip buttons.

## How it works

1. **You** send a screen recording to the bot, with a short caption like `how to add a proxy in Telegram`.
2. **Gemini** watches it once and lists the steps and where you tapped.
3. **DeepSeek** writes a short voice-over, a caption and hashtags for each language.
4. **edge-tts** (free) reads the voice-over aloud.
5. The video is built: 1080x1920, arrows and zoom on each tap, "Step 1, 2...", word-by-word subtitles,
   a watermark and an end screen with your channel. Slow parts are sped up; if the voice needs
   more time, the video slows down or freezes on the tap.
6. **You** get each video as a file. Tap **Approve** to get the caption to copy, then upload it to TikTok yourself.

## What each file does

| File | Job |
|---|---|
| `.env` | **All your settings** (keys, channel name, languages, voices, colors) |
| `setup.sh` | Installs everything, asks for your keys, starts the bot |
| `bot.py` | The Telegram bot: receives clips, runs every step, sends the videos with buttons |
| `analyze.py` | Gemini watches the clip |
| `script.py` | DeepSeek writes the voice-over, caption and hashtags |
| `voice.py` | edge-tts makes the voice |
| `edit.py` | Builds the video |
| `housekeeping.py` | Cost log and cleaning up old files |
| `data/input`, `data/work`, `data/output` | Clips, temporary files, finished videos (deleted after `CLEANUP_DAYS`) |
| `logs/videos.csv` | Every video made, approved or skipped, with its estimated cost |
| `logs/bot.log` | What the bot did, including errors |

## Install (once, on the VPS)

```bash
cd ~
git clone -b claude/screen-recording-tiktok-automation-4uf3a7 https://github.com/Nimku/Content-creation-project.git tiktok-maker
cd tiktok-maker
bash setup.sh
```

`setup.sh` installs ffmpeg, the Noto fonts (for Thai, Vietnamese and other scripts) and the Python
packages. It then asks for your keys (hidden while you paste) and starts the bot as a background
service. The service runs at low priority, so your proxies stay fast, and it restarts by itself
after a crash or a reboot.

## Start, stop, update

| Do this | Command |
|---|---|
| Is it running? | `systemctl status tiktok-bot` |
| Stop | `systemctl stop tiktok-bot` |
| Start | `systemctl start tiktok-bot` |
| Restart (after changing `.env`) | `systemctl restart tiktok-bot` |
| Watch what it is doing | `journalctl -u tiktok-bot -f` (Ctrl+C to leave) |
| Get the newest version | `cd ~/tiktok-maker && git pull && systemctl restart tiktok-bot` |

In Telegram, `/cost` shows the total estimated AI cost so far.

## Changing settings

Run `nano ~/tiktok-maker/.env`, change what you want, save (Ctrl+O, Enter, Ctrl+X), then
`systemctl restart tiktok-bot`. To change only the keys, run `bash setup.sh` again.

- `LANGUAGES`: for example `en,th` to make only English and Thai videos. Codes: `en id vi th ms`.
- `VOICE_EN`, `VOICE_TH`...: the voice for each language. List all voices with
  `venv/bin/edge-tts --list-voices | grep th-TH` (use a different language code in place of `th-TH`).
- `VOICE_RATE`: speaking speed (`+0%` is normal, `+10%` is a bit faster).
- `CHANNEL_NAME`: shown in the watermark, end screen and call to action.
- `ARROW_COLOR`, `SUBTITLE_COLOR`, `HIGHLIGHT_COLOR`, `STEP_LABEL_COLOR`: colors, for example `#FF3B30`.
- `ZOOM`: how much to zoom in on taps (`1.0` means no zoom).
- `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL`: must be Gemini 3.x Flash models (not 2.5).
- `RENDER_THREADS`: CPU threads used to make videos. Keep it low (`1`–`2`) to protect your proxies.
- `CLEANUP_DAYS`: files older than this are deleted automatically.

## How to record good clips

1. **Turn on "Show taps"** (only once): Settings → About phone → tap *Build number* 7 times.
   Then Settings → System → Developer options → turn on **Show taps**.
2. Use the phone's **Screen recorder** with **no audio**.
3. **Go slowly.** Wait about 1 second before and after each tap, so the steps are clear.
4. Keep clips to **15–40 seconds**, and one task per clip.
5. **Never show private things**: chats, phone numbers, or a proxy secret you don't want public.
6. Send it to the bot as a normal **video** (not as a file) so it stays under 20 MB, with a short caption
   saying what it shows.

## Costs

Gemini's free tier is fine to start with. DeepSeek uses your prepaid balance. The voices, the video editing
and Telegram are free. A clip with 5 languages costs well under 1 cent in AI calls. See `logs/videos.csv`
or send `/cost`.

## If something goes wrong

The bot messages you a short explanation. More detail: `journalctl -u tiktok-bot -n 50`.

- **"Gemini is too busy"**: Google is overloaded. Send the clip again later.
- **"refused the API key"**: run `bash setup.sh` and paste a working key.
- **"DeepSeek balance is empty"**: top up at platform.deepseek.com.
- **Nothing happens at all**: run `systemctl status tiktok-bot`. Only one copy of the bot can run
  at a time, so don't also start `python3 bot.py` by hand.
