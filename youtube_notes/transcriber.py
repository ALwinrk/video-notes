"""Speech-to-text transcription via faster-whisper.

Used as automatic fallback when no subtitles are available.
Model is bundled into the exe — no download needed.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from ffmpeg_locator import get_ffmpeg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")
_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
_COMPUTE_TYPE = "int8" if _DEVICE == "cpu" else "float16"


def _get_model_cache_dir() -> str:
    """Return the Whisper model cache directory."""
    if "HF_HOME" in os.environ:
        return os.environ["HF_HOME"]

    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "whisper_model_cache")
        if os.path.isdir(bundled):
            return bundled

    src = os.path.join(os.path.dirname(__file__), "..", "whisper_model_cache")
    src = os.path.normpath(src)
    if os.path.isdir(src):
        return src

    local = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "video-notes", "huggingface",
    )
    os.makedirs(local, exist_ok=True)
    return local


os.environ["HF_HOME"] = _get_model_cache_dir()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transcribe_audio(
    video_path: str,
    output_dir: str,
    language: str | None = None,
    *,
    cancel_event: threading.Event | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> str:
    """Extract audio from video and transcribe via Whisper."""
    def _step(status: str, pct: int) -> None:
        if progress:
            progress(status, pct)

    # --- 1. Extract audio ---
    _step("正在提取音频...", 36)
    audio_path = _extract_audio(video_path, output_dir)
    if not audio_path:
        return ""

    if cancel_event and cancel_event.is_set():
        return ""

    # --- 2. Load model ---
    _step("正在加载语音识别模型...", 38)

    # --- 3. Transcribe ---
    return _run_whisper(audio_path, language, cancel_event=cancel_event, progress=progress)


# ---------------------------------------------------------------------------
# Internal: audio extraction
# ---------------------------------------------------------------------------

def _extract_audio(video_path: str, output_dir: str) -> str | None:
    """Extract 16kHz mono WAV from video.  Returns path or None."""
    out = str(Path(output_dir) / "_audio.wav")
    ffmpeg = get_ffmpeg()
    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        out,
    ]
    logger.debug("Extracting audio: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Audio extraction failed: %s", result.stderr)
        return None
    if not Path(out).exists():
        return None
    return out


# ---------------------------------------------------------------------------
# Internal: Whisper transcription
# ---------------------------------------------------------------------------

def _run_whisper(
    audio_path: str,
    language: str | None,
    *,
    cancel_event: threading.Event | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> str:
    """Transcribe audio with faster-whisper.  Returns timestamped text."""
    def _step(status: str, pct: int) -> None:
        if progress:
            progress(status, pct)

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.error("faster-whisper not installed.")
        return ""

    try:
        _step("正在加载语音识别模型...", 38)
        model = WhisperModel(_MODEL_SIZE, device=_DEVICE, compute_type=_COMPUTE_TYPE)
    except Exception as exc:
        logger.error("Failed to load Whisper model '%s': %s", _MODEL_SIZE, exc)
        return ""

    _step("正在语音转文字...", 40)
    logger.info(
        "Transcribing audio with Whisper (%s, %s)…",
        _MODEL_SIZE, _DEVICE,
    )

    try:
        segments, _info = model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc)
        return ""

    # Build timestamped output
    lines: list[str] = []
    total_segs = 0
    for seg in segments:
        if cancel_event and cancel_event.is_set():
            return ""
        total_segs += 1
        start = _fmt_timestamp(seg.start)
        lines.append(f"[{start}] {seg.text.strip()}")
        # Update progress every 10 segments (avoid queue spam)
        if progress and total_segs % 10 == 0:
            # Progress from 40→47 during transcription
            progress(f"正在语音转文字... ({total_segs} 段)", 43)

    result = "\n".join(lines)
    logger.info("Whisper transcription complete: %d segments, %d chars",
                 len(lines), len(result))
    return result


def _fmt_timestamp(seconds: float) -> str:
    """Convert float seconds to HH:MM:SS or MM:SS.mmm format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"
