"""YouTube downloader backed by yt-dlp."""

from __future__ import annotations

import os
import re
import json
import logging
import threading
from pathlib import Path
from typing import Optional

import yt_dlp

from config import PipelineCancelled
from ffmpeg_locator import get_ffmpeg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def sanitise_filename(name: str) -> str:
    """Strip characters that are unsafe in filenames."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


# ---------------------------------------------------------------------------
# Video metadata
# ---------------------------------------------------------------------------

def get_video_info(
    url: str,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> dict:
    """Return a dict with title, description, duration, channel, etc.

    Raises RuntimeError if the video is unavailable, private, or the
    network is unreachable.
    """
    opts: dict = {"quiet": True, "no_warnings": True, "extract_flat": False}

    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc).lower()
        if "private" in msg:
            hint = "This video is private."
        elif "unavailable" in msg or "not found" in msg or "removed" in msg:
            hint = "This video is unavailable or has been removed."
        elif "login" in msg or "sign in" in msg:
            hint = "This video requires login (age-restricted or members-only)."
        else:
            hint = f"YouTube download error: {exc}"
        raise RuntimeError(hint) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Cannot reach YouTube — check your network connection.\n"
            f"Details: {exc}"
        ) from exc

    return {
        "id": info.get("id", ""),
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "duration": info.get("duration", 0),          # seconds
        "channel": info.get("channel", ""),
        "uploader": info.get("uploader", ""),
        "upload_date": info.get("upload_date", ""),
        "view_count": info.get("view_count", 0),
        "like_count": info.get("like_count", 0),
        "tags": info.get("tags") or [],
        "categories": info.get("categories") or [],
        "webpage_url": info.get("webpage_url", url),
        "thumbnail": info.get("thumbnail", ""),
    }


# ---------------------------------------------------------------------------
# File helpers — snapshot before download, diff after
# ---------------------------------------------------------------------------

def _snapshot_files(output_dir: Path, suffixes: tuple[str, ...]) -> set[str]:
    """Return a set of absolute paths matching *suffixes* in *output_dir*."""
    return {
        str(f.resolve())
        for f in output_dir.iterdir()
        if f.suffix.lower() in suffixes
    }


def _find_new_file(
    output_dir: Path, suffixes: tuple[str, ...], before: set[str]
) -> Optional[str]:
    """Return the first NEW file matching *suffixes* not present in *before*."""
    for f in sorted(output_dir.iterdir()):
        if f.suffix.lower() in suffixes and str(f.resolve()) not in before:
            return str(f)
    return None


# ---------------------------------------------------------------------------
# Subtitle parsing
# ---------------------------------------------------------------------------

def parse_subtitles(filepath: str) -> str:
    """Parse a VTT or SRT file into plain text with timestamp markers.

    Returns one string where each cue is prefixed with its start time.
    """
    path = Path(filepath)
    if not path.exists():
        return ""

    raw = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".vtt":
        return _parse_vtt(raw)
    return _parse_srt(raw)


# Regex to strip VTT inline tags: <c>, </c>, <00:00:01.439>,
# <i>, <b>, <v Speaker>, and any other HTML/XML tag.
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _strip_vtt_tags(text: str) -> str:
    """Remove WebVTT inline tags and normalize whitespace."""
    text = _VTT_TAG_RE.sub("", text)
    return " ".join(text.split())


def _parse_vtt(raw: str) -> str:
    """Minimal WebVTT parser – strips headers, tags & extracts cues."""
    lines: list[str] = []
    in_cue = False
    cue_lines: list[str] = []

    for line in raw.splitlines():
        # Skip header block
        if not in_cue and ("-->" in line):
            in_cue = True
            timestamps = line.strip()
            cue_lines = [f"[{timestamps.split(' --> ')[0]}]"]
            continue

        if in_cue:
            stripped = line.strip()
            if stripped == "":
                # End of cue
                if len(cue_lines) > 1:
                    lines.append(" ".join(cue_lines))
                in_cue = False
                cue_lines = []
            elif not stripped.startswith("NOTE") and not stripped.startswith("Kind:"):
                # Drop VTT metadata lines like NOTE / Kind: captions
                if not re.match(r"^[\w-]+:", stripped):
                    # Strip inline tags before adding
                    clean = _strip_vtt_tags(stripped)
                    if clean:
                        cue_lines.append(clean)

    # Flush last cue
    if in_cue and len(cue_lines) > 1:
        lines.append(" ".join(cue_lines))

    return "\n".join(lines)


def _parse_srt(raw: str) -> str:
    """Minimal SRT parser."""
    lines: list[str] = []
    cue_lines: list[str] = []
    in_text = False

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "":
            if in_text and cue_lines:
                lines.append(" ".join(cue_lines))
            in_text = False
            cue_lines = []
            continue

        if "-->" in stripped:
            in_text = True
            ts = stripped.split(" --> ")[0]
            cue_lines = [f"[{ts}]"]
        elif in_text and not stripped.isdigit():
            cue_lines.append(stripped)

    if in_text and cue_lines:
        lines.append(" ".join(cue_lines))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Video download
# ---------------------------------------------------------------------------

def download_video(
    url: str,
    output_dir: str,
    *,
    max_height: int = 1080,
    cancel_event: threading.Event | None = None,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> str:
    """Download the video (capped at *max_height* for efficiency) and return path.

    If *cancel_event* is set during download, aborts as soon as possible.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot existing .mp4 files BEFORE download
    before = _snapshot_files(out_dir, (".mp4",))

    tmpl = str(out_dir / "%(id)s.%(ext)s")

    # Progress hook: check cancellation on each progress update
    def _progress_hook(d: dict) -> None:
        if cancel_event and cancel_event.is_set():
            from config import PipelineCancelled
            raise PipelineCancelled("Cancelled by user")

    # Tell yt-dlp where our bundled ffmpeg lives
    _ffmpeg_exe = get_ffmpeg()
    _ffmpeg_dir = str(Path(_ffmpeg_exe).parent)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/best",
        "outtmpl": tmpl,
        "merge_output_format": "mp4",
        "progress_hooks": [_progress_hook],
        "ffmpeg_location": _ffmpeg_dir,
    }
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except PipelineCancelled:
        raise

    # Return the NEW file (not a stale one from a previous run)
    new = _find_new_file(out_dir, (".mp4",), before)
    if new:
        return new

    # Fallback: find by video id (exact match, not substring)
    video_id = info.get("id", "")
    for f in sorted(out_dir.iterdir()):
        if f.suffix.lower() == ".mp4" and f.stem == video_id:
            return str(f)

    raise FileNotFoundError(
        f"No .mp4 found in {out_dir} after download. "
        f"Video id: {video_id}"
    )
