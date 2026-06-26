"""Multi-channel subtitle fetcher with platform-aware routing.

YouTube:
  1. youtube-transcript-api (lightweight, no login needed for public videos)
  2. yt-dlp + cookies (full power, with browser cookie extraction)
  3. Invidious public instances (alternative frontend, no login)

Other platforms (Bilibili, TikTok, Facebook, etc.):
  1. yt-dlp (native built-in extractors for 1000+ sites)

Returns the first successful subtitle file path, or None.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional
import threading

import yt_dlp

from ffmpeg_locator import get_ffmpeg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Invidious public instances (updated periodically)
# ---------------------------------------------------------------------------

_INVIDIOUS_INSTANCES = [
    "https://invidious.privacyredirect.com",
    "https://inv.nadeko.net",
    "https://invidious.drgns.space",
    "https://yewtu.be",
    "https://vid.puffyan.us",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_subtitles(
    url: str,
    output_dir: str,
    languages: list[str],
    *,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    cancel_event: threading.Event | None = None,
) -> Optional[str]:
    """Fetch subtitles for *url* using the best available method.

    Returns the path to a .vtt/.srt file, or None.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    is_youtube = _is_youtube(url)

    if is_youtube:
        chain = [
            lambda: _via_youtube_transcript_api(url, languages, output_dir),
            lambda: _via_ytdlp(url, output_dir, languages, cookies_from_browser, cookies_file),
            lambda: _via_invidious(url, languages, output_dir),
        ]
    else:
        chain = [
            lambda: _via_ytdlp(url, output_dir, languages, cookies_from_browser, cookies_file),
        ]

    for idx, fetcher in enumerate(chain):
        if cancel_event and cancel_event.is_set():
            return None
        try:
            result = fetcher()
            if result:
                logger.info("Subtitle fetched via method %d", idx + 1)
                return result
        except Exception as exc:
            logger.debug("Subtitle method %d failed: %s", idx + 1, exc)
            continue

    logger.warning("All subtitle methods exhausted for %s", url)
    return None


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def _is_youtube(url: str) -> bool:
    """Check if URL is a YouTube video."""
    return bool(re.search(r"(youtube\.com|youtu\.be)", url, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Method 1: youtube-transcript-api
# ---------------------------------------------------------------------------

def _via_youtube_transcript_api(
    url: str, languages: list[str], output_dir: str
) -> Optional[str]:
    """Try the lightweight youtube-transcript-api library.

    This often works even when yt-dlp fails because it uses a different
    approach to fetch transcripts.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.debug("youtube-transcript-api not installed — skipping.")
        return None

    # Extract video ID from various YouTube URL formats
    video_id = _extract_youtube_id(url)
    if not video_id:
        logger.debug("Could not extract YouTube video ID from: %s", url)
        return None

    try:
        # Fetch transcript (prefer manual over auto-generated)
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try manual first, then auto-generated
        transcript = None
        for lang in languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except Exception:
                continue

        if transcript is None:
            # Try any available transcript
            try:
                transcript = transcript_list.find_manually_created_transcript()
            except Exception:
                try:
                    transcript = transcript_list.find_generated_transcript()
                except Exception:
                    return None

        if transcript is None:
            return None

        # Fetch and save as VTT-like format
        segments = transcript.fetch()
        out_path = Path(output_dir) / f"{video_id}_transcript.vtt"
        _save_as_vtt(segments, str(out_path))
        return str(out_path)

    except Exception as exc:
        logger.debug("youtube-transcript-api failed: %s", exc)
        return None


def _extract_youtube_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _save_as_vtt(segments, path: str) -> None:
    """Save transcript segments as a WebVTT file."""
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = _fmt_vtt_time(seg.get("start", 0))
        end = _fmt_vtt_time(seg.get("start", 0) + seg.get("duration", 2))
        text = seg.get("text", "").replace("\n", " ")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _fmt_vtt_time(seconds: float) -> str:
    """Format seconds to WebVTT timestamp HH:MM:SS.mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


# ---------------------------------------------------------------------------
# Method 2: yt-dlp (with optional cookies)
# ---------------------------------------------------------------------------

def _via_ytdlp(
    url: str,
    output_dir: str,
    languages: list[str],
    cookies_from_browser: str | None,
    cookies_file: str | None,
) -> Optional[str]:
    """Download subtitles via yt-dlp.

    Uses cookies from browser or file if provided.
    """
    out = Path(output_dir)
    tmpl = os.path.join(output_dir, "%(id)s.%(ext)s")

    # Snapshot before download
    before = _snapshot_files(out, (".vtt", ".srt"))

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": languages,
        "subtitlesformat": "vtt",
        "outtmpl": tmpl,
        "skip_download": True,
    }

    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        logger.debug("yt-dlp subtitle download failed: %s", exc)
        return None

    return _find_new_file(out, (".vtt", ".srt"), before)


# ---------------------------------------------------------------------------
# Method 3: Invidious API
# ---------------------------------------------------------------------------

def _via_invidious(
    url: str, languages: list[str], output_dir: str
) -> Optional[str]:
    """Try to get subtitles via Invidious public instances."""
    import urllib.request
    import urllib.error
    import json as _json

    video_id = _extract_youtube_id(url)
    if not video_id:
        return None

    for instance in _INVIDIOUS_INSTANCES:
        try:
            api_url = f"{instance}/api/v1/videos/{video_id}"
            req = urllib.request.Request(api_url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())

            captions = data.get("captions", [])
            if not captions:
                continue

            # Find matching language
            for lang in languages:
                for cap in captions:
                    if cap.get("languageCode", "").startswith(lang.split("-")[0]):
                        cap_url = cap.get("url", "")
                        if cap_url:
                            return _download_invidious_caption(
                                cap_url, video_id, output_dir
                            )

        except (urllib.error.URLError, Exception) as exc:
            logger.debug("Invidious instance %s failed: %s", instance, exc)
            continue

    return None


def _download_invidious_caption(
    cap_url: str, video_id: str, output_dir: str
) -> Optional[str]:
    """Download and save an Invidious caption as VTT."""
    import urllib.request
    import urllib.error
    import json as _json

    try:
        req = urllib.request.Request(cap_url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())

        # Build VTT
        lines = ["WEBVTT", ""]
        for cue in data.get("cues", []):
            start = _fmt_vtt_time(cue.get("start", 0))
            end = _fmt_vtt_time(cue.get("start", 0) + cue.get("dur", 2))
            text = cue.get("text", "").replace("\n", " ")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        out_path = Path(output_dir) / f"{video_id}_invidious.vtt"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return str(out_path)

    except Exception as exc:
        logger.debug("Invidious caption download failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _snapshot_files(output_dir: Path, suffixes: tuple[str, ...]) -> set[str]:
    """Return a set of absolute paths matching *suffixes* in *output_dir*."""
    if not output_dir.exists():
        return set()
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
