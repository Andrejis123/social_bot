"""
OpenAI classifier (fallback / per-client override).

Caveats vs. Gemini:
- GPT-4o / GPT-4.1 accept images via base64 data URLs but DO NOT natively
  accept raw video bytes. For Reels/videos we skip video frames here and
  rely on the caption alone. If a client insists on OpenAI for video,
  revisit with frame-sampling (extract N frames, send as images).
- JSON schema enforcement via `response_format={"type": "json_schema"...}`.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from openai import OpenAI

from ...config import get_settings
from ...logging import get_logger
from .gemini import ClassifyResult, MediaBlob

log = get_logger(__name__)


def classify_with_openai(
    *,
    prompt: str,
    media: list[MediaBlob],
    categories: list[str],
) -> ClassifyResult:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=settings.openai_api_key)

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for blob in media:
        if not blob.mime_type.startswith("image/"):
            log.warning("openai.skip_non_image", mime=blob.mime_type)
            continue
        b64 = base64.b64encode(blob.bytes_data).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{blob.mime_type};base64,{b64}"},
            }
        )

    schema = {
        "name": "post_classification",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "category": {"type": "string", "enum": categories} if categories else {"type": "string"},
                "confidence": {"type": ["number", "null"]},
                "reasoning": {"type": ["string", "null"]},
            },
            "required": ["category", "confidence", "reasoning"],
        },
    }

    resp = client.chat.completions.create(  # type: ignore[call-overload]  # SDK overload stub; valid at runtime
        model=settings.openai_model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": schema},
    )
    text = resp.choices[0].message.content or "{}"
    data = json.loads(text)

    return ClassifyResult(
        category=str(data["category"]),
        confidence=_coerce_float(data.get("confidence")),
        reasoning=data.get("reasoning"),
        provider="openai",
    )


def describe_with_openai(
    *,
    prompt: str,
    media: list[MediaBlob],
) -> str:
    """Return a free-form description string for a post."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=settings.openai_api_key)

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for blob in media:
        if not blob.mime_type.startswith("image/"):
            log.warning("openai.skip_non_image", mime=blob.mime_type)
            continue
        b64 = base64.b64encode(blob.bytes_data).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{blob.mime_type};base64,{b64}"},
            }
        )

    schema = {
        "name": "post_description",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    }

    resp = client.chat.completions.create(  # type: ignore[call-overload]  # SDK overload stub; valid at runtime
        model=settings.openai_model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": schema},
    )
    text = resp.choices[0].message.content or "{}"
    data = json.loads(text)
    return str(data["description"])


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
