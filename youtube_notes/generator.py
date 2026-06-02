"""Note generation – formats analysis results and saves to disk."""

from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime

from downloader import sanitise_filename


def save_notes(text: str, output_dir: str, title: str, metadata: dict | None = None) -> str:
    """Write notes to a plain text file and return the absolute path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    safe_title = sanitise_filename(title)
    safe_title = re.sub(r"_+", "_", safe_title)[:80]

    # If title collapses to empty after sanitising, fall back to video id
    if not safe_title or safe_title in ("_", ""):
        if metadata:
            safe_title = sanitise_filename(metadata.get("title", "")) or metadata.get("id", "untitled")
        else:
            safe_title = "untitled"

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{date_str}_{safe_title}.txt"
    filepath = out / filename

    filepath.write_text(text, encoding="utf-8")
    return str(filepath.resolve())


def wrap_notes(raw_notes: str, metadata: dict) -> str:
    """Add a metadata header to the raw notes."""
    title = metadata.get("title", "Untitled")
    channel = metadata.get("channel", metadata.get("uploader", "Unknown"))
    duration = metadata.get("duration", 0)
    url = metadata.get("webpage_url", "")

    mins, secs = divmod(int(duration), 60)
    hours, mins = divmod(mins, 60)
    if hours:
        dur_str = f"{hours}h {mins}m {secs}s"
    else:
        dur_str = f"{mins}m {secs}s"

    header = (
        f"[视频信息]\n"
        f"标题: {title}\n"
        f"频道: {channel}\n"
        f"时长: {dur_str}\n"
        f"来源: {url}\n"
        f"生成时间: {datetime.now().isoformat()}\n"
        "\n"
    )
    return header + raw_notes.strip()
