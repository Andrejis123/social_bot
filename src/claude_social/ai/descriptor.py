"""
Per-post AI descriptor.

Separate from the classifier — this job runs after ingestion, fetches media
from Supabase Storage (CDN URLs expire; storage paths don't), and asks the AI
for a thorough neutral description of what the post shows.

The description is used at report-generation time to synthesise narrative
paragraphs across multiple posts.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..logging import get_logger
from .providers.gemini import MediaBlob, describe_with_gemini
from .providers.openai import describe_with_openai

log = get_logger(__name__)

_PROMPT = """\
You are analysing an Instagram post for a social media monitoring report.

Describe this post thoroughly and objectively. Include:
- What the visual content shows: people, settings, objects, on-screen text, visible branding
- Any named people, brands, events, places, or products that appear or are mentioned
- The format and style (e.g. lifestyle photo, flat lay, reel with text overlays, interview video)
- The apparent message or theme being communicated
- Any call to action, interactive element, hashtag campaign, or promotional mechanic

Caption: {caption}
Post type: {post_type}

Be specific and factual. Write 3–5 sentences. Do not classify or judge the content — only describe it.
"""


@dataclass(slots=True)
class DescribeResult:
    description: str
    provider: str


def describe(
    *,
    caption: str | None,
    post_type: str,
    blobs: list[MediaBlob],
    provider: str = "gemini",
) -> DescribeResult:
    """Return a thorough description of the post. Raises on unrecoverable failure."""
    prompt = _PROMPT.format(
        caption=caption or "(no caption)",
        post_type=post_type,
    )

    if provider == "openai":
        text = describe_with_openai(prompt=prompt, media=blobs)
        return DescribeResult(description=text, provider="openai")

    try:
        text = describe_with_gemini(prompt=prompt, media=blobs)
        return DescribeResult(description=text, provider="gemini")
    except Exception as exc:
        log.warning("descriptor.gemini.failed_falling_back_to_openai", error=str(exc))
        text = describe_with_openai(prompt=prompt, media=blobs)
        return DescribeResult(description=text, provider="openai")
