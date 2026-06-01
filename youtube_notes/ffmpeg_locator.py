"""Locate ffmpeg and ffprobe — bundled copies preferred, fall back to system PATH."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _bundled_dir() -> str | None:
    """Return the directory containing bundled ffmpeg/ffprobe, or None."""
    # PyInstaller extracts bundled binaries to sys._MEIPASS
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return meipass
    # Running from source: check alongside this module
    return str(Path(__file__).resolve().parent)


def get_ffmpeg() -> str:
    """Return path to ffmpeg executable.

    Checks bundled copy first, then system PATH.
    Raises RuntimeError if not found.
    """
    bundled = _bundled_dir()
    if bundled:
        bundled_exe = os.path.join(bundled, "ffmpeg.exe")
        if os.path.isfile(bundled_exe):
            return bundled_exe

    system = shutil.which("ffmpeg")
    if system:
        return system

    raise RuntimeError(
        "未找到 ffmpeg！\n"
        "ffmpeg 是提取视频帧所必需的。\n"
        "安装方法：winget install ffmpeg\n"
        "或从 https://ffmpeg.org/download.html 下载"
    )


def get_ffprobe() -> str:
    """Return path to ffprobe executable.

    Checks bundled copy first, then system PATH.
    Raises RuntimeError if not found.
    """
    bundled = _bundled_dir()
    if bundled:
        bundled_exe = os.path.join(bundled, "ffprobe.exe")
        if os.path.isfile(bundled_exe):
            return bundled_exe

    system = shutil.which("ffprobe")
    if system:
        return system

    # ffprobe is usually alongside ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
        if os.path.isfile(ffprobe):
            return ffprobe

    raise RuntimeError(
        "未找到 ffprobe！\n"
        "ffprobe 通常和 ffmpeg 一起安装。\n"
        "安装方法：winget install ffmpeg"
    )
