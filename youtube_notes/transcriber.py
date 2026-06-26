"""Speech-to-text transcription — cloud-first with local fallback.

Priority chain (auto-degrading):
  1. Groq Whisper (whisper-large-v3-turbo) — free tier, fastest
  2. OpenAI Whisper API (whisper-1) — $0.006/min
  3. whisper.cpp tiny (local ~75 MB) — offline, free

The chain stops at the first successful transcription.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from ffmpeg_locator import get_ffmpeg
from config import TranscriberProvider, TRANSCRIBER_CONFIG, UsageTracker

logger = logging.getLogger(__name__)


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
    """Extract audio from video, then transcribe via the provider chain.

    Returns timestamped text, or empty string on total failure.
    """
    def _step(status: str, pct: int) -> None:
        if progress:
            progress(status, pct)

    # --- 1. Extract audio ---
    _step("正在提取音频...", 36)
    audio_path = _extract_audio(video_path, output_dir)
    if not audio_path:
        logger.error("Audio extraction failed — cannot transcribe.")
        return ""

    if cancel_event and cancel_event.is_set():
        return ""

    # --- 2. Build provider chain ---
    chain = _build_chain()

    # --- 3. Run chain ---
    for idx, provider in enumerate(chain):
        if cancel_event and cancel_event.is_set():
            return ""

        cfg = TRANSCRIBER_CONFIG.get(provider, {})
        name = cfg.get("display_name", provider.value)
        _step(f"正在语音转文字（{name}）...", 38 + idx * 2)

        try:
            result = _transcribe_with(provider, audio_path, language, output_dir)
        except Exception as exc:
            logger.warning("Transcriber %s failed: %s", provider.value, exc)
            continue

        if result:
            # Record usage for tracking
            _record_usage(provider, audio_path, output_dir)
            _step(f"语音识别完成（{name}，{len(result)} 字符）", 48)
            return result

        logger.info("Transcriber %s returned empty result, trying next...", provider.value)

    return ""


# ---------------------------------------------------------------------------
# Provider chain builder
# ---------------------------------------------------------------------------

def _build_chain() -> list[TranscriberProvider]:
    """Build the transcription provider chain based on available API keys."""
    chain: list[TranscriberProvider] = []

    # Groq — needs GROQ_API_KEY
    if os.environ.get("GROQ_API_KEY"):
        chain.append(TranscriberProvider.GROQ)

    # OpenAI Whisper — needs OPENAI_API_KEY
    if os.environ.get("OPENAI_API_KEY"):
        chain.append(TranscriberProvider.OPENAI_WHISPER)

    # Local whisper.cpp always available as fallback (if binary + model exist)
    chain.append(TranscriberProvider.LOCAL_WHISPER)

    return chain


# ---------------------------------------------------------------------------
# Individual providers
# ---------------------------------------------------------------------------

def _transcribe_with(
    provider: TranscriberProvider,
    audio_path: str,
    language: str | None,
    output_dir: str,
) -> str:
    """Dispatch to the appropriate transcription backend."""
    if provider == TranscriberProvider.GROQ:
        return _transcribe_groq(audio_path, language)
    elif provider == TranscriberProvider.OPENAI_WHISPER:
        return _transcribe_openai_whisper(audio_path, language)
    elif provider == TranscriberProvider.LOCAL_WHISPER:
        return _transcribe_whisper_cpp(audio_path, language, output_dir)
    else:
        raise ValueError(f"Unknown transcriber: {provider}")


# ---------------------------------------------------------------------------
# Groq Whisper (OpenAI-compatible API)
# ---------------------------------------------------------------------------

def _transcribe_groq(audio_path: str, language: str | None) -> str:
    """Transcribe via Groq's Whisper API (OpenAI-compatible)."""
    from openai import OpenAI

    api_key = os.environ.get("GROQ_API_KEY", "")
    cfg = TRANSCRIBER_CONFIG[TranscriberProvider.GROQ]
    client = OpenAI(api_key=api_key, base_url=cfg["api_base"])

    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model=cfg["model"],
            file=f,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    return _format_verbose_json(resp)


# ---------------------------------------------------------------------------
# OpenAI Whisper API
# ---------------------------------------------------------------------------

def _transcribe_openai_whisper(audio_path: str, language: str | None) -> str:
    """Transcribe via OpenAI's Whisper API."""
    from openai import OpenAI

    cfg = TRANSCRIBER_CONFIG[TranscriberProvider.OPENAI_WHISPER]
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model=cfg["model"],
            file=f,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    return _format_verbose_json(resp)


def _format_verbose_json(resp) -> str:
    """Convert OpenAI verbose_json response to timestamped text lines."""
    lines: list[str] = []
    segments = getattr(resp, "segments", [])
    for seg in segments:
        start = _fmt_timestamp(seg.start)
        text = seg.text.strip()
        if text:
            lines.append(f"[{start}] {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# whisper.cpp local (subprocess)
# ---------------------------------------------------------------------------

def _find_whisper_cpp() -> str | None:
    """Locate the whisper.cpp CLI binary.

    Checks: bundled path, system PATH, and common install locations.
    """
    # 1. Bundled with PyInstaller
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "whisper.cpp.exe")
        if os.path.isfile(bundled):
            return bundled

    # 2. Alongside source
    local = Path(__file__).resolve().parent / "whisper.cpp.exe"
    if local.exists():
        return str(local)

    # 3. System PATH
    import shutil
    system = shutil.which("whisper.cpp")
    if system:
        return system

    return None


def _find_whisper_model() -> str | None:
    """Locate the whisper.cpp GGML model file (tiny)."""
    model_name = "ggml-tiny.bin"

    # 1. Bundled with PyInstaller
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, model_name)
        if os.path.isfile(bundled):
            return bundled

    # 2. Alongside source
    local = Path(__file__).resolve().parent / model_name
    if local.exists():
        return str(local)

    # 3. In models/ subdirectory
    models_dir = Path(__file__).resolve().parent / "models"
    candidate = models_dir / model_name
    if candidate.exists():
        return str(candidate)

    return None


def _transcribe_whisper_cpp(
    audio_path: str, language: str | None, output_dir: str
) -> str:
    """Transcribe using local whisper.cpp CLI."""
    exe = _find_whisper_cpp()
    if not exe:
        logger.warning("whisper.cpp binary not found — local transcription unavailable.")
        return ""

    model = _find_whisper_model()
    if not model:
        logger.warning("whisper.cpp model (ggml-tiny.bin) not found.")
        return ""

    # Build command
    cmd = [
        exe,
        "-m", model,
        "-f", audio_path,
        "-oj",          # JSON output
        "-of", str(Path(output_dir) / "_whisper_output"),
    ]
    if language:
        lang_code = language.split("-")[0] if "-" in language else language
        cmd += ["-l", lang_code]

    logger.debug("Running whisper.cpp: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        logger.error("whisper.cpp timed out after 10 minutes.")
        return ""
    except FileNotFoundError:
        logger.error("whisper.cpp executable not found at: %s", exe)
        return ""

    if result.returncode != 0:
        logger.error("whisper.cpp failed: %s", result.stderr)
        return ""

    # Parse JSON output
    json_path = Path(output_dir) / "_whisper_output.json"
    if not json_path.exists():
        logger.warning("whisper.cpp output file not found.")
        return ""

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("whisper.cpp output is not valid JSON.")
        return ""

    lines: list[str] = []
    transcriptions = data.get("transcription", [])
    for seg in transcriptions:
        t0 = seg.get("timestamps", {}).get("from", "")
        text = seg.get("text", "").strip()
        if text:
            ts = _fmt_timestamp(_parse_ts(t0))
            lines.append(f"[{ts}] {text}")

    return "\n".join(lines)


def _parse_ts(ts_str: str) -> float:
    """Parse a timestamp string like '00:01:23.456' to float seconds."""
    try:
        parts = ts_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(ts_str)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

def _record_usage(
    provider: TranscriberProvider, audio_path: str, output_dir: str
) -> None:
    """Record transcription usage for quota tracking."""
    try:
        duration = _probe_audio_duration(audio_path)
        if duration > 0:
            tracker = UsageTracker(output_dir)
            tracker.record(provider, duration)
    except Exception:
        pass


def _probe_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds via ffprobe."""
    from ffmpeg_locator import get_ffprobe
    ffprobe = get_ffprobe()
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception as exc:
        logger.debug("Audio duration probe failed: %s", exc)
    return 0.0


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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.error("Audio extraction failed: %s", result.stderr)
        return None
    if not Path(out).exists():
        return None
    return out


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------

def _fmt_timestamp(seconds: float) -> str:
    """Convert float seconds to HH:MM:SS or MM:SS.mmm format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"
