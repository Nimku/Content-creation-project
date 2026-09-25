"""Small helpers: the cost log and deleting old temporary files."""
import csv
import shutil
import time

import config

COST_LOG = config.LOG_DIR / "videos.csv"


def log_event(clip, lang, event, cost_usd=0.0):
    """Adds one line to logs/videos.csv (open it with any spreadsheet app)."""
    config.LOG_DIR.mkdir(exist_ok=True)
    new_file = not COST_LOG.exists()
    with open(COST_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["time", "clip", "language", "event", "estimated_cost_usd"])
        writer.writerow([time.strftime("%Y-%m-%d %H:%M"), clip, lang, event, f"{cost_usd:.5f}"])


def total_cost():
    if not COST_LOG.exists():
        return 0.0
    with open(COST_LOG, encoding="utf-8") as f:
        return sum(float(row["estimated_cost_usd"] or 0) for row in csv.DictReader(f))


def cleanup():
    """Deletes clips, temporary files and finished videos older than CLEANUP_DAYS."""
    cutoff = time.time() - config.CLEANUP_DAYS * 86400
    removed = 0
    for folder in (config.INPUT_DIR, config.WORK_DIR, config.OUTPUT_DIR):
        for item in folder.iterdir():
            if item.name == ".gitkeep" or item.stat().st_mtime > cutoff:
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()
            removed += 1
    return removed
