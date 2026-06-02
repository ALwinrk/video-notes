"""Frame extraction via ffmpeg."""

from __future__ import annotations

import subprocess
import logging
from pathlib import Path

from ffmpeg_locator import get_ffmpeg, get_ffprobe

logger = logging.getLogger(__name__)


def extract_frames(
    video_path: str,
    output_dir: str,
    interval_sec: int = 30,
    max_frames: int = 20,
) -> list[str]:
    """Extract evenly-spaced key-frames from *video_path*.

    Returns a sorted list of JPEG file paths.
    """
    src = Path(video_path)
    if not src.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    out = Path(output_dir) / "frames"
    out.mkdir(parents=True, exist_ok=True)

    # Figure out how many frames we should extract
    duration = _probe_duration(str(src))
    if duration <= 0:
        # Unknown duration — be conservative
        frame_count = min(10, max_frames)
    else:
        # At least 1 frame, at most max_frames
        estimated = max(1, int(duration / interval_sec))
        frame_count = min(estimated, max_frames)
        # Never request more frames than seconds in the video
        frame_count = min(frame_count, int(duration))

    # Use ffmpeg's fps filter: 1 frame every `interval_sec` seconds
    fps = f"1/{interval_sec}"
    ffmpeg = get_ffmpeg()

    cmd = [
        ffmpeg,
        "-y",                        # overwrite
        "-i", str(src),
        "-vf", f"fps={fps}",
        "-frames:v", str(frame_count),
        "-q:v", "2",                 # good JPEG quality
        f"{out}/frame_%04d.jpg",
    ]

    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("ffmpeg stderr:\n%s", result.stderr)
        raise RuntimeError(f"ffmpeg failed with code {result.returncode}")

    frames = sorted(out.glob("frame_*.jpg"))
    paths = [str(f) for f in frames]
    logger.info("Extracted %d frames → %s", len(paths), out)
    return paths


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _probe_duration(video_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    ffprobe = get_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception as exc:
        logger.debug("ffprobe duration probe failed: %s", exc)
    return 0.0
