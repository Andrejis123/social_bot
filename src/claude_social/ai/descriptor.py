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

Start with a 1-2 sentence summary capturing the main point — what the post is about \
and its primary purpose. For example: "This post announces the launch of IQOS's new \
summer campaign in Prague, inviting followers to visit their pop-up zone at the Brutal \
Assault festival."

Then describe the post in detail. Include:
- What each image or slide shows: people, settings, objects, on-screen text, visible branding
- Any named people, brands, events, places, products, or dates that appear or are mentioned
- The format and style (e.g. lifestyle photo, reel with text overlays, interview video, mixed carousel)
- The tone and emotional register (e.g. aspirational, humorous, urgent, inspirational)
- Any call to action, interactive element, hashtag campaign, or promotional mechanic

Caption: {caption}
Post type: {post_type}

Be specific and factual. Do not classify the content — only describe it. Aim for 5-8 sentences total.
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
