#!/usr/bin/env python3
"""Video Notes — download a video, extract frames, analyse with a vision LLM,
and produce structured notes.

支持 YouTube、Bilibili、Twitter/X、TikTok、Vimeo 等数千个视频网站。

Usage (CLI)
-----------
    python main.py https://www.youtube.com/watch?v=XXXXX
    python main.py URL --provider anthropic --model claude-sonnet-4-20250514
    python main.py URL --provider ollama --model llama3.2-vision --api-base http://localhost:11434

Usage (GUI)
-----------
    python main.py              (no arguments → launch GUI)
    python main.py --gui        (explicit GUI launch)
    video-notes.exe              (double-click → GUI)

Environment variables
---------------------
    OPENAI_API_KEY     – used when --provider openai and --api-key not set
    ANTHROPIC_API_KEY  – used when --provider anthropic and --api-key not set
    DEEPSEEK_API_KEY   – used when --provider deepseek and --api-key not set
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from config import Config, Provider, get_provider_info
from pipeline import run_pipeline, PipelineCancelled


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    _setup_logging(args.verbose)

    # Build config
    provider = Provider(args.provider)
    api_key = args.api_key or _auto_key(provider)
    model = args.model

    # Auto-detect local file vs URL
    url = args.url
    local_file = None
    local_path = Path(url)
    if local_path.exists() and local_path.is_file():
        local_file = str(local_path.resolve())
        _sprint(f"[INFO] 检测到本地文件: {local_file}")
        # Use filename as placeholder URL for metadata
        url = f"file://{local_file}"

    if not api_key and provider not in (Provider.OLLAMA,):
        _sprint(
            f"[WARN] No API key provided for {provider.value}. "
            f"Set --api-key or the {get_provider_info(provider).key_env} environment variable.",
            file=sys.stderr,
        )
        if not args.dry_run:
            raise SystemExit(1)

    # Build transcriber chain from CLI flag
    from config import TranscriberProvider
    tc = args.transcriber
    if tc == "groq":
        transcriber_chain = [TranscriberProvider.GROQ]
    elif tc == "openai_whisper":
        transcriber_chain = [TranscriberProvider.OPENAI_WHISPER]
    elif tc == "local":
        transcriber_chain = [TranscriberProvider.LOCAL_WHISPER]
    else:
        transcriber_chain = [
            TranscriberProvider.GROQ,
            TranscriberProvider.OPENAI_WHISPER,
            TranscriberProvider.LOCAL_WHISPER,
        ]

    cfg = Config(
        url=url,
        local_file=local_file,
        output_dir=args.output,
        provider=provider,
        model=model,
        api_key=api_key,
        api_base=args.api_base,
        frame_interval=args.frame_interval,
        max_frames=args.max_frames,
        languages=args.languages.split(","),
        note_language=args.note_language,
        keep_video=args.keep_video,
        keep_frames=args.keep_frames,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies_file,
        transcriber_chain=transcriber_chain,
        game_analysis=not args.no_game_analysis,
    )

    # --- Show metadata ---
    _sprint(f"[INFO] Fetching video info for {cfg.url} ...")
    from downloader import get_video_info
    metadata = get_video_info(cfg.url)
    _sprint(f"   Title   : {metadata['title']}")
    _sprint(f"   Channel : {metadata.get('channel', metadata.get('uploader', '?'))}")
    _sprint(f"   Duration: {_fmt_duration(metadata['duration'])}")

    if args.dry_run:
        _sprint("\n[DRY RUN] Would proceed with:")
        _sprint(f"   Provider: {cfg.provider.value} / {cfg.model}")
        _sprint(f"   Frames:  every {cfg.frame_interval}s, max {cfg.max_frames}")
        _sprint(f"   Output:  {cfg.output_dir}")
        return

    # Warn about missing vision
    if not cfg.provider.supports_vision:
        _sprint(
            f"\n[WARN] {cfg.provider.value} does not support vision (image analysis).\n"
            "       Will generate notes from transcript only.  For visual analysis,\n"
            "       use --provider openai (GPT-4o) or --provider anthropic (Claude).\n"
        )

    # --- Run pipeline with CLI progress ---
    def _cli_progress(status: str, percent: int) -> None:
        _sprint(f"   [{percent:3d}%] {status}")

    try:
        notes, output_path, _meta = run_pipeline(cfg, progress=_cli_progress)
    except PipelineCancelled:
        _sprint("\n[CANCELLED] Pipeline was cancelled.")
        raise SystemExit(1)

    _sprint(f"\n[OK] Notes saved to: {output_path}")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate structured notes from a YouTube video using vision AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py https://www.youtube.com/watch?v=dQw4w9WgXcQ
  python main.py URL -p anthropic -m claude-sonnet-4-20250514 -l zh
  python main.py URL -p ollama -m llama3.2-vision --api-base http://localhost:11434
        """,
    )

    p.add_argument("url", help="YouTube video URL")

    p.add_argument("-o", "--output", default="./notes", help="Output directory (default: ./notes)")

    # LLM
    p.add_argument(
        "-p", "--provider", default="openai",
        choices=["openai", "anthropic", "ollama", "deepseek"],
        help="LLM provider (default: openai; use deepseek for DeepSeek API)",
    )
    p.add_argument(
        "-m", "--model", default="",
        help="Model name (defaults to provider's recommended model)",
    )
    p.add_argument("-k", "--api-key", help="API key (or set env var)")
    p.add_argument("--api-base", help="Custom API base URL (for Ollama / proxies)")

    # Frame extraction
    p.add_argument(
        "--frame-interval", type=int, default=30,
        help="Seconds between extracted frames (default: 30)",
    )
    p.add_argument(
        "--max-frames", type=int, default=20,
        help="Maximum number of frames to extract (default: 20)",
    )

    # Subtitles
    p.add_argument(
        "--languages", default="en,zh-Hans,ja",
        help="Comma-separated subtitle language codes to try (default: en,zh-Hans,ja)",
    )
    p.add_argument(
        "-l", "--note-language", default="zh",
        help="Language for generated notes – 'zh', 'en', 'ja', etc. (default: zh)",
    )

    # YouTube auth
    p.add_argument(
        "--cookies-from-browser", default=None,
        help="Extract cookies from browser to bypass login (chrome, firefox, edge, brave, opera)",
    )
    p.add_argument(
        "--cookies-file", default=None,
        help="Path to cookies.txt (Netscape format) for YouTube login bypass",
    )

    # Transcription
    p.add_argument(
        "--transcriber", default="auto",
        choices=["auto", "groq", "openai_whisper", "local"],
        help="Transcription backend chain (default: auto = Groq -> OpenAI -> local)",
    )
    p.add_argument(
        "--no-game-analysis", action="store_true",
        help="Disable game-specific analysis prompt",
    )

    # Misc
    p.add_argument("--keep-video", action="store_true", help="Don't delete the video after processing")
    p.add_argument("--keep-frames", action="store_true", help="Don't delete extracted frames")
    p.add_argument("--dry-run", action="store_true", help="Fetch metadata only, don't analyse")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p.add_argument("--gui", action="store_true", help=argparse.SUPPRESS)  # hidden flag

    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_key(provider: Provider) -> str | None:
    """Read API key from environment based on provider."""
    info = get_provider_info(provider)
    if not info.key_env:
        return None
    key = os.environ.get(info.key_env)
    # Fallback: DeepSeek users often set OPENAI_API_KEY
    if not key and provider == Provider.DEEPSEEK:
        key = os.environ.get("OPENAI_API_KEY")
    return key


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _sprint(*args, **kwargs) -> None:
    """Safe print – replaces unencodable characters on Windows GBK consoles."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [str(a).encode("ascii", errors="replace").decode("ascii") for a in args]
        print(*safe_args, **kwargs)


def _pause_if_interactive() -> None:
    """Pause only if stdin is a real terminal (not a pipe or redirect)."""
    if not sys.stdin.isatty():
        return
    print("\nPress Enter to exit...", end="")
    try:
        input()
    except EOFError:
        pass


# ---------------------------------------------------------------------------
# __main__ dispatch: CLI vs GUI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Determine mode: GUI if no args / double-click, CLI otherwise
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        # GUI mode
        if "--gui" in sys.argv:
            sys.argv.remove("--gui")
        from gui import main as gui_main
        gui_main()
    else:
        # CLI mode
        try:
            main()
        except SystemExit as exc:
            if exc.code is not None and exc.code != 0:
                _pause_if_interactive()
            sys.exit(exc.code if exc.code is not None else 1)
        except Exception as exc:
            _sprint(f"\n[FATAL] {exc}", file=sys.stderr)
            logging.getLogger(__name__).exception("Unhandled error")
            _pause_if_interactive()
            sys.exit(1)
