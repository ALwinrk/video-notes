"""Shared pipeline runner — used by both CLI and GUI."""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path
from typing import Callable

from config import Config, Provider, get_provider_info, PipelineCancelled
from downloader import get_video_info, download_subtitles, download_video, parse_subtitles
from extractor import extract_frames
from analyzer import analyze
from generator import save_notes, wrap_notes
from ffmpeg_locator import get_ffmpeg
from transcriber import transcribe_audio

logger = logging.getLogger(__name__)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    """Raise PipelineCancelled if the cancel event is set."""
    if cancel_event and cancel_event.is_set():
        raise PipelineCancelled("Cancelled by user")


def run_pipeline(
    cfg: Config,
    progress: Callable[[str, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, str, dict]:
    """Run the full video-analysis pipeline.

    Parameters
    ----------
    cfg : Config
        Complete configuration.
    progress : callable(status: str, percent: int) or None
        Called after each major step.  ``percent`` ranges 0–100.
    cancel_event : threading.Event or None
        If set, raises ``PipelineCancelled`` at every checkpoint including
        during downloads and LLM analysis.
    """
    def _step(status: str, percent: int) -> None:
        if progress:
            progress(status, percent)

    video_path = ""
    frame_paths: list[str] = []

    try:
        is_local = bool(cfg.local_file)

        # --- 1. 获取视频信息 (5%) ---
        _check_cancel(cancel_event)
        if is_local:
            _step("本地文件模式...", 5)
            fname = Path(cfg.local_file).stem  # type: ignore[arg-type]
            metadata = {
                "id": fname, "title": fname, "description": "",
                "duration": 0, "channel": "本地文件", "uploader": "",
                "upload_date": "", "view_count": 0, "like_count": 0,
                "tags": [], "categories": [], "webpage_url": cfg.local_file or "",
                "thumbnail": "",
            }
        else:
            _step("正在获取视频信息...", 5)
            try:
                metadata = get_video_info(cfg.url)
            except RuntimeError as exc:
                if "login" in str(exc).lower() and cfg.use_cookies:
                    _step("需要登录，正在从 Chrome 提取 cookies...", 5)
                    metadata = get_video_info(cfg.url, cookies=True)
                else:
                    raise

        # --- 2. 检查 ffmpeg (10%) ---
        _check_cancel(cancel_event)
        _step("正在检查运行环境...", 10)
        try:
            get_ffmpeg()
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from None

        # --- 3. 验证 API 密钥 (12%) ---
        _check_cancel(cancel_event)
        _step("正在验证 API 密钥...", 12)
        _validate_api_key(cfg)

        # --- 4. 获取字幕 (20%) ---
        _check_cancel(cancel_event)
        if is_local:
            # 本地文件：无法获取外部字幕，直接走语音识别
            _step("本地文件模式，跳过字幕下载...", 20)
            transcript = ""
        else:
            _step("正在下载字幕...", 20)
            try:
                sub_path = download_subtitles(cfg.url, cfg.output_dir, cfg.languages)
            except RuntimeError as exc:
                if "login" in str(exc).lower() and cfg.use_cookies:
                    _step("需要登录，正在从 Chrome 提取 cookies...", 20)
                    sub_path = download_subtitles(cfg.url, cfg.output_dir, cfg.languages, cookies=True)
                else:
                    raise
            _check_cancel(cancel_event)
            transcript = parse_subtitles(sub_path) if sub_path else ""

        need_video = cfg.provider.supports_vision or not transcript

        # --- 5. 获取视频 (30%) ---
        _check_cancel(cancel_event)

        if is_local:
            _step("使用本地视频文件...", 30)
            video_path = cfg.local_file  # type: ignore[assignment]
            if not Path(video_path).exists():
                raise FileNotFoundError(f"本地视频文件不存在: {video_path}")
        elif need_video:
            _step("正在下载视频...", 30)
            try:
                video_path = download_video(cfg.url, cfg.output_dir, cancel_event=cancel_event)
            except RuntimeError as exc:
                if "login" in str(exc).lower() and cfg.use_cookies:
                    _step("需要登录，正在从 Chrome 提取 cookies...", 30)
                    video_path = download_video(cfg.url, cfg.output_dir, cookies=True, cancel_event=cancel_event)
                else:
                    raise
            _check_cancel(cancel_event)
        else:
            _step("跳过视频下载（有字幕且无需视觉分析）...", 30)

        # --- 6. 字幕缺失 → 语音识别回退 (35-50%) ---
        if not transcript and video_path:
            _check_cancel(cancel_event)
            _step("未找到字幕，启动语音识别...", 35)
            logger.info("No subtitles available — falling back to Whisper transcription.")
            lang_hint = cfg.languages[0] if cfg.languages else None
            if lang_hint and '-' in lang_hint:
                lang_hint = lang_hint.split('-')[0]
            transcript = transcribe_audio(
                video_path, cfg.output_dir,
                language=lang_hint,
                cancel_event=cancel_event,
                progress=progress,
            )
            _check_cancel(cancel_event)
            if transcript:
                _step(f"语音识别完成（{len(transcript)} 字符）", 48)
            else:
                _step("语音识别失败，继续尝试分析...", 48)

        # --- 7. 提取关键帧（仅视觉平台）(50-55%) ---
        _check_cancel(cancel_event)

        if cfg.provider.supports_vision and video_path:
            _step("正在提取关键帧...", 52)
            frame_paths = extract_frames(
                video_path, cfg.output_dir, cfg.frame_interval, cfg.max_frames
            )

        _step("预处理完成", 55)

        # --- 8. AI 分析 (55-80%) ---
        if not transcript and not frame_paths:
            raise RuntimeError(
                "无法分析：视频没有字幕/语音，且当前平台不支持视觉分析。\n"
                "建议：换用 OpenAI 或 Anthropic（支持视觉），或选择包含语音的视频。"
            )
        _check_cancel(cancel_event)
        _step(f"正在用 {cfg.provider.value} / {cfg.model} 分析...", 55)
        raw_notes = analyze(transcript, frame_paths, metadata, cfg, cancel_event=cancel_event)
        _check_cancel(cancel_event)
        _step("AI 分析完成", 80)

        # --- 9. 生成笔记 (85-95%) ---
        _check_cancel(cancel_event)
        _step("正在生成笔记文件...", 85)
        notes = wrap_notes(raw_notes, metadata)
        output_path = save_notes(notes, cfg.output_dir, metadata["title"], metadata)

        # --- 10. 清理 (95-99%) ---
        _check_cancel(cancel_event)
        _step("正在清理临时文件...", 95)
        _cleanup(video_path, frame_paths, cfg)

        _step("完成", 100)
        return notes, output_path, metadata

    except PipelineCancelled:
        _step("已取消", 0)
        try:
            _cleanup(video_path, frame_paths, cfg)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Fast cleanup
# ---------------------------------------------------------------------------

def _cleanup(video_path: str, frame_paths: list[str], cfg: Config) -> None:
    """Remove temporary files, silently ignoring errors.

    Never delete the user's local file — only downloaded videos.
    """
    is_local = bool(cfg.local_file)
    if video_path and not cfg.keep_video and not is_local:
        try:
            Path(video_path).unlink(missing_ok=True)
        except Exception:
            pass
    # Clean up temporary audio from Whisper transcription
    audio_path = Path(cfg.output_dir) / "_audio.wav"
    if audio_path.exists():
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass
    if not cfg.keep_frames:
        frames_dir = Path(cfg.output_dir) / "frames"
        if frames_dir.exists():
            try:
                shutil.rmtree(frames_dir, ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Internal: API key validation
# ---------------------------------------------------------------------------

def _validate_api_key(cfg: Config) -> None:
    """Quickly verify the API key is valid before downloading anything."""
    if cfg.provider == Provider.OLLAMA:
        return

    if cfg.provider in (Provider.OPENAI, Provider.DEEPSEEK):
        _validate_openai(cfg)
    elif cfg.provider == Provider.ANTHROPIC:
        _validate_anthropic(cfg)


def _validate_openai(cfg: Config) -> None:
    try:
        from openai import OpenAI, AuthenticationError
        import httpx
        info = get_provider_info(cfg.provider)
        client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.api_base or info.default_api_base,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
    except AuthenticationError:
        _fail_key(cfg.provider)
    except Exception as exc:
        _fail_network(cfg.provider, exc)


def _validate_anthropic(cfg: Config) -> None:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.api_key, base_url=cfg.api_base)
        client.messages.create(
            model=cfg.model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except anthropic.AuthenticationError:
        _fail_key(cfg.provider)
    except Exception as exc:
        _fail_network(cfg.provider, exc)


def _fail_key(provider: Provider) -> None:
    info = get_provider_info(provider)
    env = info.key_env or "API_KEY"
    raise RuntimeError(
        f"{info.display_name} API key is invalid or expired.\n"
        f"Get a valid key and set it with: set {env}=your-key"
    )


def _fail_network(provider: Provider, exc: Exception) -> None:
    info = get_provider_info(provider)
    raise RuntimeError(
        f"Cannot reach {info.display_name} API: {exc}\n"
        "Check your network, API base URL, and model name."
    )
