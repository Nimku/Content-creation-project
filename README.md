# TikTok Tutorial Maker

Turns your phone screen recordings into short vertical TikTok tutorials
(AI voice, arrows, subtitles) in several languages, and sends them to you
on Telegram for approval.

> Work in progress: built one step at a time. Right now **step 1
> (Gemini watches the clip)** works. More sections will be added as each
> step is finished.

## What each file does

| File | Job |
|---|---|
| `.env` | **All your settings** (keys, channel name, languages, voices, colors) |
| `config.py` | Reads `.env` so the other files can use it |
| `analyze.py` | Sends the clip to Gemini and gets the list of steps and tap positions |
| `script.py` | *(coming)* DeepSeek writes the voice-over, caption, and hashtags |
| `voice.py` | *(coming)* edge-tts makes the narration |
| `edit.py` | *(coming)* builds the 1080x1920 video |
| `bot.py` | *(coming)* the Telegram bot: receives clips, sends videos with buttons |
| `data/input` | Clips you send to the bot |
| `data/work` | Temporary files (cleaned up automatically) |
| `data/output` | Finished videos |
| `logs/` | Log of each video made and what it cost |

## Install (once, on the VPS)

```bash
cd ~
git clone -b claude/screen-recording-tiktok-automation-4uf3a7 https://github.com/Nimku/Content-creation-project.git tiktok-maker
cd tiktok-maker
bash setup.sh
```

`setup.sh` installs ffmpeg, the Noto fonts (Thai, Vietnamese, and other scripts) and the
Python packages, then asks for your keys (hidden while you paste) and saves them in `.env`.
Run `bash setup.sh` again any time to change a key.

Every time you log in again over SSH, run `cd ~/tiktok-maker && source venv/bin/activate` first.

## Test step 1: Gemini watches a clip

Copy a recording to the VPS (for example, from Termux:
`scp /sdcard/Movies/clip.mp4 root@YOUR_VPS_IP:tiktok-maker/data/input/`), then run:

```bash
python3 analyze.py data/input/clip.mp4 "how to add a proxy in Telegram"
```

You should see something like:

```
Found 4 steps in 18.2s of video:
  Step 1:   0.0s -   3.1s  Open Telegram settings  (tap at x=0.92, y=0.07)
  ...
Estimated Gemini cost: $0.0040
```

The answer is saved to `data/work/clip/steps.json`. Running the command again
reuses that file and costs nothing. Add `--fresh` to make Gemini look at the clip again.

## Changing settings

Everything is in `.env`. Edit it with `nano .env`. Changes take effect the next time
the program starts.

- `GEMINI_MODEL`: must be a Gemini 3.x Flash model. Do not use 2.5.
- `GEMINI_FPS`: how many frames per second Gemini looks at. If quick taps are missed, try `3` or `4`. Higher values cost a little more.
- `LANGUAGES`: for example `en,th` to make only English and Thai versions.
