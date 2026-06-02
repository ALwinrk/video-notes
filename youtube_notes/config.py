"""Configuration for YouTube Notes generator."""

from dataclasses import dataclass, field
from enum import Enum
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
        default_api_base="https://api.highwayapi.ai/openai",
        default_model="gpt-4o-mini",
        supports_vision=True,
        models=["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-4.1", "o3", "o4-mini"],
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

    # Cleanup
    keep_video: bool = False
    keep_frames: bool = False

    # Transcript cap (characters) — longer transcripts are summarised first
    max_transcript_chars: int = 30_000

    # Cookie — auto-retry with Chrome cookies on age-restricted / members-only videos
    use_cookies: bool = False

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
