"""Vision + text analysis via LLM (OpenAI / Anthropic / Ollama / DeepSeek)."""

from __future__ import annotations

import base64
import functools
import io
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image

from config import Config, Provider, get_provider_info

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _retry_call(
    fn: Callable[[], str],
    max_retries: int = 2,
    backoff: float = 1.0,
) -> str:
    """Call *fn*, retrying on transient errors with exponential backoff.

    Does NOT retry on authentication errors (4xx) — only network / 5xx.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except RuntimeError:
            # Authentication / permanent errors — don't retry
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = backoff * (2 ** attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, delay, exc,
                )
                time.sleep(delay)
    raise RuntimeError(
        f"LLM call failed after {max_retries + 1} attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# System prompt template (extracted from code for maintainability)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are an assistant that extracts game update information from YouTube videos.
The video is a game update / patch notes / dev log. Your job is to identify and list
EVERY update item mentioned, so the user can write official patch notes.

{vision_note}
## Rules (strict)
- Write in {note_language}.
- NO markdown formatting: do NOT use # * ** ` > or any other markup symbols. Plain text only.
- Use numbers and line breaks to separate items. No bullet symbols.
- Every update item MUST include a timestamp from the transcript.
- List ALL changes mentioned — new features, fixes, balance changes, UI updates, events, etc.
- Be specific: include numbers, names, durations, percentages if mentioned.
- Do NOT summarise vaguely. Do NOT add commentary, opinions, or suggestions.
- Do NOT invent content that is not in the video.

## Output structure

[视频信息]
标题: <title>
频道: <channel>
时长: <duration>

[更新摘要]
Write a concise overview of what this update is about in 2-3 sentences.

[更新内容列表]
For every single change mentioned, write one line with timestamp:
HH:MM:SS - 具体更新内容描述

Example:
03:22 - 新增英雄"影"，被动技能每3次普攻触发额外伤害
05:10 - 排位赛段位奖励调整，钻石段位新增限定皮肤
07:45 - 修复了组队时语音断连的bug
12:30 - 限时活动"夏日庆典"7月15日至7月30日开启

[浓缩总结]
Take ALL the items from [更新内容列表] above and condense them into ONE cohesive paragraph (not a list). Keep every key detail — numbers, names, dates, percentages — do NOT lose anything important. Write it as a smooth narrative summary ready to be used as game patch notes. No markdown, plain text only.
"""


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

def encode_frame(path: str, max_size: int = 768) -> str:
    """Resize a frame to *max_size* (longest edge) and return base64 data-URL."""
    img = Image.open(path)
    img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# LLM client factory
# ---------------------------------------------------------------------------

def _make_client(cfg: Config):
    """Return a callable `(system_prompt, user_content_parts) -> str`."""
    if cfg.provider == Provider.OPENAI:
        return _OpenAIClient(cfg, base_url="https://api.openai.com/v1")
    elif cfg.provider == Provider.DEEPSEEK:
        return _OpenAIClient(cfg, base_url="https://api.deepseek.com")
    elif cfg.provider == Provider.ANTHROPIC:
        return _AnthropicClient(cfg)
    elif cfg.provider == Provider.OLLAMA:
        return _OllamaClient(cfg)
    else:
        raise ValueError(f"Unknown provider: {cfg.provider}")


# ---------------------------------------------------------------------------
# OpenAI-compatible client (OpenAI + DeepSeek)
# ---------------------------------------------------------------------------

class _OpenAIClient:
    def __init__(self, cfg: Config, base_url: str = ""):
        from openai import OpenAI
        kwargs: dict = {"api_key": cfg.api_key}
        kwargs["base_url"] = cfg.api_base or base_url
        self.client = OpenAI(**kwargs)
        self.model = cfg.model

    def __call__(self, system: str, user_parts: list[dict]) -> str:
        from openai import AuthenticationError
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_parts},
        ]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=4096,
        )
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------

class _AnthropicClient:
    def __init__(self, cfg: Config):
        import anthropic
        kwargs = {"api_key": cfg.api_key}
        if cfg.api_base:
            kwargs["base_url"] = cfg.api_base
        self.client = anthropic.Anthropic(**kwargs)
        self.model = cfg.model

    def __call__(self, system: str, user_parts: list[dict]) -> str:
        import anthropic
        # Convert OpenAI-style parts → Anthropic content blocks
        content: list[dict] = []
        for part in user_parts:
            if part["type"] == "text":
                content.append({"type": "text", "text": part["text"]})
            elif part["type"] == "image_url":
                b64 = part["image_url"]["url"]
                if b64.startswith("data:"):
                    b64 = b64.split(",", 1)[1]
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64,
                    },
                })

        try:
            resp = self.client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": content}],
                temperature=0.3,
                max_tokens=4096,
            )
        except anthropic.AuthenticationError:
            raise RuntimeError(
                "Anthropic API key is invalid or expired.\n"
                "Get a valid key at: https://console.anthropic.com/\n"
                "Then set it with: set ANTHROPIC_API_KEY=sk-ant-your-key"
            ) from None

        for block in resp.content:
            if block.type == "text":
                return block.text

        logger.warning("Anthropic returned no text content blocks (got %d blocks)", len(resp.content))
        return ""


# ---------------------------------------------------------------------------
# Ollama client (local)
# ---------------------------------------------------------------------------

class _OllamaClient:
    def __init__(self, cfg: Config):
        self.base = cfg.api_base or "http://localhost:11434"
        self.model = cfg.model

    def __call__(self, system: str, user_parts: list[dict]) -> str:
        import urllib.request
        import urllib.error
        import socket

        # Build Ollama chat payload
        messages = [{"role": "system", "content": system}]
        text_parts = [p["text"] for p in user_parts if p["type"] == "text"]
        image_parts = [
            p["image_url"]["url"].split(",", 1)[1]
            if "," in p["image_url"]["url"]
            else p["image_url"]["url"]
            for p in user_parts if p["type"] == "image_url"
        ]

        if image_parts:
            messages.append({
                "role": "user",
                "content": "\n\n".join(text_parts),
                "images": image_parts,
            })
        else:
            messages.append({
                "role": "user",
                "content": "\n\n".join(text_parts),
            })

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3},
        }).encode()

        req = urllib.request.Request(
            f"{self.base}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
                return data.get("message", {}).get("content", "")
        except urllib.error.URLError as exc:
            reason = str(exc.reason).lower() if exc.reason else str(exc)
            if "refused" in reason or "connection" in reason:
                raise RuntimeError(
                    f"Cannot connect to Ollama at {self.base}.\n"
                    "Is Ollama running? Start it with: ollama serve"
                ) from exc
            raise RuntimeError(
                f"Ollama request failed: {exc}\n"
                f"Check that Ollama is running at {self.base}"
            ) from exc
        except socket.timeout as exc:
            raise RuntimeError(
                f"Ollama request timed out (300s). Try a smaller model or shorter video."
            ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    transcript: str,
    frame_paths: list[str],
    metadata: dict,
    cfg: Config,
    *,
    cancel_event: threading.Event | None = None,
) -> str:
    """Run vision + transcript analysis and return generated notes."""
    client = _make_client(cfg)

    # ------------------------------------------------------------------
    # Step 1 – maybe summarise long transcripts
    # ------------------------------------------------------------------
    if len(transcript) > cfg.max_transcript_chars:
        logger.info("Transcript too long (%d chars), summarising first…", len(transcript))
        transcript = _summarise_transcript(transcript, metadata, client, cfg, cancel_event=cancel_event)
        logger.info("Condensed transcript → %d chars", len(transcript))

    if cancel_event and cancel_event.is_set():
        from config import PipelineCancelled
        raise PipelineCancelled("Cancelled by user")

    # ------------------------------------------------------------------
    # Step 2 – encode frames as base64
    # ------------------------------------------------------------------
    image_parts: list[dict] = []
    use_vision = cfg.provider.supports_vision and frame_paths

    if use_vision:
        for fp in frame_paths:
            try:
                b64 = encode_frame(fp)
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })
            except Exception as exc:
                logger.warning("Failed to encode frame %s: %s", fp, exc)

    # ------------------------------------------------------------------
    # Step 3 – build prompt and call LLM
    # ------------------------------------------------------------------
    system_prompt = _build_system_prompt(cfg, has_vision=use_vision)

    user_parts: list[dict] = [
        {"type": "text", "text": _build_user_prompt(metadata, transcript, has_vision=use_vision)},
    ] + image_parts

    logger.info(
        "Calling %s model %s with %d frames and %d chars of transcript…",
        cfg.provider.value, cfg.model, len(image_parts), len(transcript),
    )

    def _call() -> str:
        try:
            return client(system_prompt, user_parts)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            raise RuntimeError(
                f"{cfg.provider.value} API call failed: {exc}\n"
                "Check your network, API key, and model name."
            ) from exc

    return _retry_call(_call)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_system_prompt(cfg: Config, *, has_vision: bool = True) -> str:
    vision_note = ""
    if not has_vision:
        vision_note = (
            "\n**Note**: Video frames are NOT available — analyse based on the transcript alone. "
            "Infer visual context from the speaker's words where possible.\n"
        )

    return _SYSTEM_PROMPT_TEMPLATE.format(
        note_language=cfg.note_language,
        vision_note=vision_note,
    )


def _build_user_prompt(metadata: dict, transcript: str, *, has_vision: bool = True) -> str:
    title = metadata.get("title", "Unknown")
    channel = metadata.get("channel", metadata.get("uploader", "Unknown"))
    duration = metadata.get("duration", 0)
    mins, secs = divmod(int(duration), 60)
    hours, mins = divmod(mins, 60)
    dur_str = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"

    desc = metadata.get("description", "")
    if len(desc) > 500:
        desc = desc[:500] + "…"

    frame_note = (
        "Analyse the transcript together with the key frames below."
        if has_vision
        else "Analyse the transcript below. Video frames are unavailable."
    )

    return f"""\
Video metadata:
Title: {title}
Channel: {channel}
Duration: {dur_str}
Description: {desc}

Transcript:
{transcript}

---
{frame_note}
List every update item with timestamps. No markdown, plain text only.
"""


# ---------------------------------------------------------------------------
# Transcript summarisation (for long videos)
# ---------------------------------------------------------------------------

def _summarise_transcript(
    transcript: str,
    metadata: dict,
    client,
    cfg: Config,
    *,
    cancel_event: threading.Event | None = None,
) -> str:
    """Chunk and summarise a long transcript, then merge summaries."""
    lines = transcript.splitlines()
    chunk_size = 200
    chunks = [
        "\n".join(lines[i:i + chunk_size])
        for i in range(0, len(lines), chunk_size)
    ]

    summaries: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        # Check cancel between each chunk
        if cancel_event and cancel_event.is_set():
            from config import PipelineCancelled
            raise PipelineCancelled("Cancelled by user")

        system = (
            f"You are a transcriber. Summarise this video transcript chunk concisely "
            f"in {cfg.note_language}. Keep all timestamps. Preserve key facts, numbers, and names."
        )
        user = f"Chunk {idx}/{len(chunks)}:\n\n{chunk}"
        try:
            s = client(system, [{"type": "text", "text": user}])
            summaries.append(s)
        except PipelineCancelled:
            raise
        except Exception as exc:
            logger.warning("Chunk %d summarisation failed: %s", idx, exc)
            summaries.append(chunk[:500])

    if cancel_event and cancel_event.is_set():
        from config import PipelineCancelled
        raise PipelineCancelled("Cancelled by user")

    merge_prompt = (
        f"Combine the following chunk summaries into one coherent transcript summary "
        f"in {cfg.note_language}. Keep all timestamps and key details.\n\n"
        + "\n\n---\n\n".join(summaries)
    )

    try:
        merged = client(
            "You are an editor. Merge these summaries into one coherent transcript.",
            [{"type": "text", "text": merge_prompt}],
        )
        return merged
    except PipelineCancelled:
        raise
    except Exception:
        return "\n\n".join(summaries)
