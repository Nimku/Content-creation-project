"""STEP 5 - EDIT
Builds the finished 1080x1920 TikTok video for one language:
- the screen recording, gently zoomed in on each tap
- an animated circle + arrow at each tap
- "Step 1", "Step 2"... labels
- big word-by-word subtitles (the current word is highlighted)
- a small watermark and an end screen with the channel name
- the voice-over, lined up with the steps: boring parts are sped up (up to 3x),
  and if the voice is longer than the step, the video slows a little and then
  freezes on the tap until the sentence is finished.

Try it by itself (after voice.py):
    python3 edit.py data/input/clip.mp4 en
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

W, H = 1080, 1920
FPS = 30
LEAD = 0.5        # each step's part starts this many seconds before the tap
PAD = 0.35        # short silence after each spoken sentence
MAX_SPEED = 3.0   # parts with nothing to say play up to 3x faster
MIN_SPEED = 0.8   # parts with too much to say play up to 20% slower, then freeze

STEP_WORD = {"en": "Step", "id": "Langkah", "vi": "Bước", "th": "ขั้นตอนที่", "ms": "Langkah"}
JOIN_TEXT = {"en": "Join on Telegram", "id": "Gabung di Telegram", "vi": "Tham gia trên Telegram",
             "th": "เข้าร่วมใน Telegram", "ms": "Sertai di Telegram"}

# ---------- fonts (Noto: covers Thai, Vietnamese, Indonesian, Malay, English) ----------
FONT_DIRS = [config.FONT_DIR, Path("/usr/share/fonts/truetype/noto"), Path("/usr/share/fonts/opentype/noto")]
THAI = re.compile("[฀-๿]")
_fonts = {}


def font(size, thai=False):
    name = "NotoSansThai-Bold.ttf" if thai else "NotoSans-Bold.ttf"
    if (name, size) not in _fonts:
        path = next((d / name for d in FONT_DIRS if (d / name).exists()), None)
        if not path:
            raise RuntimeError(f"Font {name} is missing. Run: apt install fonts-noto-core")
        _fonts[(name, size)] = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.RAQM
                                                  if _has_raqm() else ImageFont.Layout.BASIC)
    return _fonts[(name, size)]


def _has_raqm():
    from PIL import features
    return features.check("raqm")


def pieces_by_script(text):
    """Splits text into Thai and non-Thai parts: the Thai font has no Latin letters or digits."""
    return re.findall(r"[\u0E00-\u0E7F]+|[^\u0E00-\u0E7F]+", text)


def text_width(draw, text, size):
    return sum(draw.textlength(p, font=font(size, bool(THAI.match(p)))) for p in pieces_by_script(text))


def draw_text(draw, x, baseline, text, size, fill, stroke=0, center=False):
    """Draws text (mixing Thai and Latin fonts as needed) with its baseline at `baseline`."""
    if center:
        x -= text_width(draw, text, size) / 2
    for p in pieces_by_script(text):
        f = font(size, bool(THAI.match(p)))
        draw.text((x, baseline), p, font=f, anchor="ls", fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
        x += draw.textlength(p, font=f)


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------- timeline: which part of the recording plays when, and when each sentence is spoken ----------
def build_timeline(analysis, voice):
    duration, steps = analysis["duration"], analysis["steps"]
    starts, prev = [], None
    for s in steps:
        a = max(s["start"] - LEAD, 0.0 if prev is None else prev + 0.1)
        starts.append(min(a, duration - 0.1))
        prev = starts[-1]

    windows = [(0.0, starts[0], 0.0, voice["hook"], None)]  # the hook plays over the opening
    for i, s in enumerate(steps):
        b = starts[i + 1] if i + 1 < len(steps) else duration
        tap_moment = min(max(s["start"] + 0.15, starts[i]), b)
        windows.append((starts[i], b, tap_moment, voice["lines"][i], i))

    pieces, speech, spans, t = [], [], [], 0.0
    for a, b, freeze_at, part, step_index in windows:
        length = max(b - a, 0.0)
        need = part["duration"] + PAD + 0.1 if part else 0.0
        begin = t
        if part:
            speech.append((t + 0.1, part))
        if length >= need and length > 0.01:
            speed = min(max(length / need, 1.0), MAX_SPEED) if need else MAX_SPEED
            pieces.append(("play", t, t + length / speed, a, speed))
            t += length / speed
        elif need > 0:
            speed = max(length / need, MIN_SPEED) if length > 0.01 else 1.0
            before, after = (freeze_at - a) / speed, (b - freeze_at) / speed
            if before > 0:
                pieces.append(("play", t, t + before, a, speed))
                t += before
            hold = max(need - length / speed, 0.0)
            pieces.append(("freeze", t, t + hold, freeze_at, 0))
            t += hold
            if after > 0:
                pieces.append(("play", t, t + after, freeze_at, speed))
                t += after
        if step_index is not None:
            spans.append((begin, t, step_index))

    end_start = t
    cta = voice["cta"]
    if cta:
        speech.append((t + 0.3, cta))
    total = t + max((cta["duration"] if cta else 0) + 1.0, 2.5)
    return {"pieces": pieces, "speech": speech, "spans": spans, "end_start": end_start, "total": total}


def source_time(timeline, t, src_duration):
    for kind, t0, t1, a, speed in timeline["pieces"]:
        if t < t1:
            s = a if kind == "freeze" else a + (t - t0) * speed
            return min(max(s, 0.0), src_duration - 0.05)
    return src_duration - 0.05


# ---------- subtitles: split each sentence into short chunks of words ----------
def make_chunks(start, part, lang):
    words = [dict(w, start=start + w["start"], end=start + w["end"]) for w in part["words"]]
    chunks, current = [], []
    for w in words:
        joined = "".join(x["text"] for x in current + [w])
        if current and (len(current) >= 3 or len(joined) > 16):
            chunks.append(current)
            current = []
        current.append(w)
    if current:
        chunks.append(current)
    result = []
    for i, c in enumerate(chunks):
        until = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else start + part["duration"] + 0.3
        result.append((c[0]["start"], until, c))
    return result


def draw_words(img, words, current, center_y, lang):
    """Draws one subtitle chunk centred on the screen, with the current word in the highlight colour."""
    draw = ImageDraw.Draw(img)
    texts = [w["text"] for w in words]
    for size in range(88, 40, -4):
        # Thai is written without spaces between words
        gaps = [0 if (lang == "th" and THAI.search(texts[i]) and THAI.search(texts[i + 1])) else size * 0.3
                for i in range(len(texts) - 1)] + [0]
        widths = [text_width(draw, x, size) for x in texts]
        if sum(widths) + sum(gaps) <= W - 100:
            break
    x = (W - sum(widths) - sum(gaps)) / 2
    white, yellow = rgb(config.SUBTITLE_COLOR), rgb(config.HIGHLIGHT_COLOR)
    for i, text in enumerate(texts):
        draw_text(draw, x, center_y, text, size, yellow if words[i] is current else white, max(size // 12, 4))
        x += widths[i] + gaps[i]


# ---------- small pictures made once and pasted on every frame ----------
def pill(text, color, size):
    w, h = int(text_width(ImageDraw.Draw(Image.new("RGBA", (1, 1))), text, size)) + size, int(size * 1.6)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=color)
    draw_text(d, w / 2, h / 2 + size * 0.36, text, size, (255, 255, 255), center=True)
    return img


def watermark():
    text = config.CHANNEL_NAME
    img = Image.new("RGBA", (W, 70), (0, 0, 0, 0))
    draw_text(ImageDraw.Draw(img), W / 2, 50, text, 40, (255, 255, 255, 150), 2, center=True)
    return img


def draw_pointer(draw, x, y, t):
    """Pulsing circle at the tap, and a bouncing arrow pointing at it."""
    color = rgb(config.ARROW_COLOR)
    r = 58 + 10 * math.sin(t * 2 * math.pi * 1.5)
    draw.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255), width=14)
    draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=8)
    # the arrow comes from below-right; from the left or from above if it would leave the screen
    dx = -1 if x > W - 280 else 1
    dy = -1 if y > H - 420 else 1
    reach = (r + 20 + 14 * math.sin(t * 2 * math.pi * 2)) * 0.707
    tip = (x + dx * reach, y + dy * reach)
    tail = (tip[0] + dx * 150, tip[1] + dy * 150)
    for width, fill in ((26, (255, 255, 255)), (16, color)):
        draw.line((tail, tip), fill=fill, width=width)
    ux, uy = tip[0] - tail[0], tip[1] - tail[1]
    n = math.hypot(ux, uy) or 1
    ux, uy = ux / n, uy / n
    head = [tip, (tip[0] - 50 * ux + 30 * uy, tip[1] - 50 * uy - 30 * ux),
            (tip[0] - 50 * ux - 30 * uy, tip[1] - 50 * uy + 30 * ux)]
    draw.polygon(head, fill=color, outline=(255, 255, 255))


def ease(p):
    p = min(max(p, 0.0), 1.0)
    return p * p * (3 - 2 * p)


# ---------- the video ----------
def render(analysis, script, voice, out_path):
    from moviepy import AudioFileClip, CompositeAudioClip, VideoClip, VideoFileClip

    lang = script["lang"]
    steps = analysis["steps"]
    timeline = build_timeline(analysis, voice)
    src = VideoFileClip(analysis["video"], audio=False)
    sw, sh = src.size
    scale = min(W / sw, H / sh)
    bw, bh = int(sw * scale) // 2 * 2, int(sh * scale) // 2 * 2
    ox, oy = (W - bw) // 2, (H - bh) // 2

    # blurred, darkened background made from the first frame (fills the space around the recording)
    first = Image.fromarray(src.get_frame(0))
    cover = max(W / sw, H / sh)
    bg = first.resize((int(sw * cover) + 1, int(sh * cover) + 1)).crop((0, 0, W, H))
    bg = Image.blend(bg.filter(ImageFilter.GaussianBlur(40)), Image.new("RGB", (W, H), (0, 0, 0)), 0.55)

    step_word = STEP_WORD.get(lang, "Step")
    labels = [pill(f"{step_word} {i + 1}", rgb(config.STEP_LABEL_COLOR), 60) for i in range(len(steps))]
    mark = watermark()
    chunks = [c for start, part in timeline["speech"] for c in make_chunks(start, part, lang)]
    join = JOIN_TEXT.get(lang, JOIN_TEXT["en"])

    def frame(t):
        img = bg.copy()
        span = next((s for s in timeline["spans"] if s[0] <= t < s[1]), None)
        step = steps[span[2]] if span else None
        tap = step and step["tap_x"] is not None

        if t < timeline["end_start"]:
            pic = Image.fromarray(src.get_frame(source_time(timeline, t, src.duration)))
            # gentle zoom towards the tap, in at the start of the step and out at the end
            z = 1.0
            if tap:
                z = 1 + (config.ZOOM - 1) * ease((t - span[0]) / 0.6) * ease((span[1] - t) / 0.4)
            cw, ch = sw / z, sh / z
            cx, cy = (step["tap_x"] * sw, step["tap_y"] * sh) if tap else (sw / 2, sh / 2)
            x0 = min(max(cx - cw / 2, 0), sw - cw)
            y0 = min(max(cy - ch / 2, 0), sh - ch)
            if z > 1.001:
                pic = pic.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
            img.paste(pic.resize((bw, bh), Image.BILINEAR), (ox, oy))
            draw = ImageDraw.Draw(img)
            sub_y = int(H * 0.80)
            if tap:
                px, py = ox + (cx - x0) / cw * bw, oy + (cy - y0) / ch * bh
                draw_pointer(draw, px, py, t - span[0])
                if H * 0.66 < py < H * 0.88:
                    sub_y = int(H * 0.36)  # keep subtitles off the tapped button
            if span:
                label = labels[span[2]]
                img.paste(label, ((W - label.width) // 2, 110), label)
            img.paste(mark, (0, H - 110), mark)
        else:
            # end screen
            draw = ImageDraw.Draw(img)
            pop = 0.85 + 0.15 * ease((t - timeline["end_start"]) / 0.4)
            draw_text(draw, W / 2, H * 0.40, config.CHANNEL_NAME, int(110 * pop),
                      rgb(config.HIGHLIGHT_COLOR), 6, center=True)
            draw_text(draw, W / 2, H * 0.40 + 110, join, 60, (255, 255, 255), 4, center=True)
            sub_y = int(H * 0.72)

        chunk = next((c for c in chunks if c[0] <= t < c[1]), None)
        if chunk:
            current = next((w for w in reversed(chunk[2]) if w["start"] <= t), chunk[2][0])
            draw_words(img, chunk[2], current, sub_y, lang)
        return np.asarray(img)

    sounds = [AudioFileClip(p["file"]) for _, p in timeline["speech"]]
    audio = CompositeAudioClip([a.with_start(s) for a, (s, _) in zip(sounds, timeline["speech"])])
    video = VideoClip(frame, duration=timeline["total"]).with_audio(audio.with_duration(timeline["total"]))
    video.write_videofile(
        str(out_path), fps=FPS, codec="libx264", audio_codec="aac", preset="veryfast",
        threads=config.RENDER_THREADS, logger=None,
        ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    )
    for clip in [src, *sounds]:
        clip.close()  # stops the background ffmpeg readers
    return {"file": str(out_path), "duration": timeline["total"]}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 edit.py <video.mp4> <language code, e.g. en>")
        sys.exit(1)
    stem, lang = Path(sys.argv[1]).stem, sys.argv[2]
    work = config.WORK_DIR / stem
    load = lambda name: json.loads((work / name).read_text(encoding="utf-8"))
    out = config.OUTPUT_DIR / f"{stem}_{lang}.mp4"
    result = render(load("steps.json"), load(f"script_{lang}.json"), load(f"voice_{lang}.json"), out)
    print(f"Made {out} ({result['duration']:.1f}s)")
