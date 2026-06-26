"""Configuration for YouTube Notes generator."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Shared exception — used by pipeline & downloader without circular imports
# ---------------------------------------------------------------------------

class PipelineCancelled(Exception):
    """Raised when the user cancels the pipeline mid-run."""


class Provider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    DEEPSEEK = "deepseek"

    @property
    def supports_vision(self) -> bool:
        """Whether this provider's models can analyse images."""
        return self is not Provider.DEEPSEEK


class TranscriberProvider(Enum):
    """Speech-to-text transcription backend."""
    GROQ = "groq"            # Groq Whisper API — free tier, fastest
    OPENAI_WHISPER = "openai_whisper"  # OpenAI Whisper API — $0.006/min
    LOCAL_WHISPER = "local"  # whisper.cpp tiny — offline, free


class VideoType(Enum):
    """Classification of a video by subtitle + audio availability."""
    FULL = "full"                # subtitles + audio
    SUBTITLED = "subtitled"      # subtitles only, no audio track
    AUDIO_ONLY = "audio_only"    # no subtitles, has audio
    VISUAL_ONLY = "visual_only"  # no subtitles, no audio — frames only


# ---------------------------------------------------------------------------
# Per-provider metadata — single source of truth
# ---------------------------------------------------------------------------

@dataclass
class ProviderInfo:
    """Metadata for one LLM provider."""
    display_name: str           # human-readable name
    key_env: str | None         # environment variable for API key (None = local/Ollama)
    default_api_base: str | None  # provider's default endpoint (None = use SDK default)
    default_model: str          # default model name
    supports_vision: bool       # provider-wide vision support flag
    models: list[str]           # known model names (empty = editable / user-typed)


PROVIDER_CONFIG: dict[Provider, ProviderInfo] = {
    Provider.OPENAI: ProviderInfo(
        display_name="OpenAI",
        key_env="OPENAI_API_KEY",
        default_api_base="https://api.openai.com/v1",
        default_model="gpt-4o",
        supports_vision=True,
        models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4.1", "o3", "o4-mini"],
    ),
    Provider.ANTHROPIC: ProviderInfo(
        display_name="Anthropic",
        key_env="ANTHROPIC_API_KEY",
        default_api_base=None,
        default_model="claude-sonnet-4-20250514",
        supports_vision=True,
        models=[
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ],
    ),
    Provider.DEEPSEEK: ProviderInfo(
        display_name="DeepSeek",
        key_env="DEEPSEEK_API_KEY",
        default_api_base="https://api.deepseek.com",
        default_model="deepseek-chat",
        supports_vision=False,
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    Provider.OLLAMA: ProviderInfo(
        display_name="Ollama",
        key_env=None,
        default_api_base="http://localhost:11434",
        default_model="llama3.2-vision",
        supports_vision=True,
        models=[],  # user types custom model name
    ),
}


def get_provider_info(provider: Provider) -> ProviderInfo:
    """Look up metadata for a provider."""
    if provider not in PROVIDER_CONFIG:
        raise ValueError(f"Unknown provider: {provider}")
    return PROVIDER_CONFIG[provider]


# ---------------------------------------------------------------------------
# Transcriber provider metadata
# ---------------------------------------------------------------------------

TRANSCRIBER_CONFIG: dict[TranscriberProvider, dict] = {
    TranscriberProvider.GROQ: {
        "display_name": "Groq Whisper",
        "key_env": "GROQ_API_KEY",
        "model": "whisper-large-v3-turbo",
        "api_base": "https://api.groq.com/openai/v1",
        "free_minutes_per_month": 1000,
        "cost_per_minute": 0.0,  # free tier
    },
    TranscriberProvider.OPENAI_WHISPER: {
        "display_name": "OpenAI Whisper",
        "key_env": "OPENAI_API_KEY",
        "model": "whisper-1",
        "api_base": "https://api.openai.com/v1",
        "free_minutes_per_month": 0,
        "cost_per_minute": 0.006,
    },
    TranscriberProvider.LOCAL_WHISPER: {
        "display_name": "whisper.cpp 本地",
        "key_env": None,
        "model": "tiny",
        "api_base": None,
        "free_minutes_per_month": 999999,  # unlimited
        "cost_per_minute": 0.0,
    },
}


# ---------------------------------------------------------------------------
# Usage tracker — persists monthly transcription minutes to disk
# ---------------------------------------------------------------------------

class UsageTracker:
    """Track monthly transcription usage for each provider.

    Persists to ``<output_dir>/_usage.json`` so it survives restarts.
    """

    def __init__(self, storage_dir: str = ".") -> None:
        self._path = Path(storage_dir) / "_usage.json"
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def _current_month_key(self) -> str:
        return time.strftime("%Y-%m")

    def record(self, provider: TranscriberProvider, audio_duration_sec: float) -> None:
        """Record *audio_duration_sec* seconds of transcription used."""
        key = self._current_month_key()
        pkey = provider.value
        if key not in self._data:
            self._data[key] = {}
        if pkey not in self._data[key]:
            self._data[key][pkey] = 0.0
        self._data[key][pkey] += audio_duration_sec / 60.0
        self._save()

    def minutes_this_month(self, provider: TranscriberProvider) -> float:
        """Return total minutes used for *provider* this month."""
        key = self._current_month_key()
        return self._data.get(key, {}).get(provider.value, 0.0)

    def is_exhausted(self, provider: TranscriberProvider) -> bool:
        """Check if *provider* has exceeded its free monthly limit."""
        cfg = TRANSCRIBER_CONFIG.get(provider, {})
        limit = cfg.get("free_minutes_per_month", 0)
        if limit == 0:
            return False
        return self.minutes_this_month(provider) >= limit

    def exhaustion_message(self, provider: TranscriberProvider) -> str | None:
        """Return a warning message if provider is exhausted, else None."""
        if not self.is_exhausted(provider):
            return None
        cfg = TRANSCRIBER_CONFIG.get(provider, {})
        name = cfg.get("display_name", provider.value)
        minutes = int(self.minutes_this_month(provider))
        return (
            f"{name} 免费额度已用尽（本月已用 {minutes} 分钟）。\n"
            "建议切换到 OpenAI Whisper ($0.006/分钟) 或使用本地 whisper.cpp。"
        )


# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """All user-configurable parameters for the pipeline."""

    # Required
    url: str

    # Optional: skip download, use a local video file directly
    local_file: Optional[str] = None

    # Output
    output_dir: str = "./notes"

    # LLM settings
    provider: Provider = Provider.OPENAI
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    api_base: Optional[str] = None  # for Ollama / custom endpoints

    # Frame extraction
    frame_interval: int = 30  # seconds between frames
    max_frames: int = 20      # hard cap on frame count

    # Subtitle languages (yt-dlp codes; tried in order)
    languages: list[str] = field(default_factory=lambda: ["en", "zh-Hans", "ja"])

    # Output language for generated notes
    note_language: str = "zh"

    # YouTube auth (for login-required / age-restricted videos)
    cookies_from_browser: Optional[str] = None  # chrome, firefox, edge, brave, opera
    cookies_file: Optional[str] = None          # path to cookies.txt (Netscape format)

    # Transcription settings
    transcriber_chain: list[TranscriberProvider] = field(
        default_factory=lambda: [
            TranscriberProvider.GROQ,
            TranscriberProvider.OPENAI_WHISPER,
            TranscriberProvider.LOCAL_WHISPER,
        ]
    )

    # Game analysis mode — enables game-specific prompt with categories
    game_analysis: bool = True

    # Cleanup
    keep_video: bool = False
    keep_frames: bool = False

    # Transcript cap (characters) — longer transcripts are summarised first
    max_transcript_chars: int = 30_000

    # Detected video type (set by pipeline after probing)
    video_type: VideoType = VideoType.FULL

    def __post_init__(self) -> None:
        """Validate and normalise configuration."""
        # --- Normalise provider to enum ---
        if isinstance(self.provider, str):
            self.provider = Provider(self.provider)

        # --- Normalise api_base: empty string → None ---
        if isinstance(self.api_base, str) and self.api_base.strip() == "":
            self.api_base = None

        # --- Apply provider defaults when not specified ---
        info = get_provider_info(self.provider)
        if not self.api_base:
            self.api_base = info.default_api_base

        # Auto-detect model if it's still the argparse default for the wrong provider
        if self.model == "gpt-4o" and self.provider != Provider.OPENAI:
            self.model = info.default_model
        if not self.model:
            self.model = info.default_model

        # --- Validate numeric ranges ---
        if self.frame_interval < 1:
            raise ValueError(f"frame_interval must be >= 1, got {self.frame_interval}")
        if self.max_frames < 1:
            raise ValueError(f"max_frames must be >= 1, got {self.max_frames}")
        if self.max_transcript_chars < 1000:
            raise ValueError(f"max_transcript_chars must be >= 1000, got {self.max_transcript_chars}")
        if not self.note_language:
            raise ValueError("note_language must be a non-empty language code (e.g. 'zh', 'en')")
        if not self.url:
            raise ValueError("url is required")
