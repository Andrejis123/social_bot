"""
Gemini classifier (default AI provider).

Why Gemini first:
- Native support for video input (Reels + regular videos) at lower cost than
  GPT-4o for the same payload.
- Structured JSON output via `response_schema` = reliable parsing.

Inline media has a ~20MB cap. Anything bigger is logged and skipped from the
request (the prompt + remaining items still go through). Moving to the File
API is a Phase 2 enhancement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from ...config import get_settings
from ...logging import get_logger

log = get_logger(__name__)

_INLINE_MAX_BYTES = 18 * 1024 * 1024  # conservative of the 20MB Gemini limit


@dataclass(slots=True)
class MediaBlob:
    bytes_data: bytes
    mime_type: str     # 'image/jpeg', 'video/mp4', etc.


@dataclass(slots=True)
class ClassifyResult:
    category: str
    confidence: float | None
    reasoning: str | None
    provider: str = "gemini"


def classify_with_gemini(
    *,
    prompt: str,
    media: list[MediaBlob],
    categories: list[str],
) -> ClassifyResult:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=settings.gemini_api_key)

    parts: list[types.Part] = [types.Part.from_text(text=prompt)]
    for blob in media:
        if len(blob.bytes_data) > _INLINE_MAX_BYTES:
            log.warning(
                "gemini.media.too_large_for_inline",
                bytes=len(blob.bytes_data),
                mime=blob.mime_type,
            )
            continue
        parts.append(
            types.Part.from_bytes(data=blob.bytes_data, mime_type=blob.mime_type)
        )

    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": categories} if categories else {"type": "string"},
            "confidence": {"type": "number"},
            "reasoning": {"type": "string"},
        },
        "required": ["category"],
    }

    _RETRY_DELAYS = [2, 5, 15]

    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            import time
            log.warning("gemini.retry", attempt=attempt, delay=delay)
            time.sleep(delay)
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            text = (response.text or "").strip()
            data = json.loads(text)
            return ClassifyResult(
                category=str(data["category"]),
                confidence=_coerce_float(data.get("confidence")),
                reasoning=data.get("reasoning"),
            )
        except Exception as exc:
            msg = str(exc)
            if any(code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                last_exc = exc
                continue
            raise

    raise last_exc  # type: ignore[misc]


def describe_with_gemini(
    *,
    prompt: str,
    media: list[MediaBlob],
) -> str:
    """Return a free-form description string for a post."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=settings.gemini_api_key)

    parts: list[types.Part] = [types.Part.from_text(text=prompt)]
    for blob in media:
        if len(blob.bytes_data) > _INLINE_MAX_BYTES:
            log.warning(
                "gemini.media.too_large_for_inline",
                bytes=len(blob.bytes_data),
                mime=blob.mime_type,
            )
            continue
        parts.append(
            types.Part.from_bytes(data=blob.bytes_data, mime_type=blob.mime_type)
        )

    schema = {
        "type": "object",
        "properties": {"description": {"type": "string"}},
        "required": ["description"],
    }

    _RETRY_DELAYS = [2, 5, 15]

    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            import time
            log.warning("gemini.retry", attempt=attempt, delay=delay)
            time.sleep(delay)
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            text = (response.text or "").strip()
            data = json.loads(text)
            return str(data["description"])
        except Exception as exc:
            msg = str(exc)
            if any(code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                last_exc = exc
                continue
            raise

    raise last_exc  # type: ignore[misc]


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
