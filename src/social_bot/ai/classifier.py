"""
Per-client AI classifier.

Flow:
    1. Render the client's prompt template (`prompt.md`) with the category list.
    2. Pick which media items to send (carousel sampling etc.).
    3. Download each sampled media item's bytes from its source_url.
    4. Dispatch to the provider picked in `client.yaml` (gemini | openai).
    5. Return `{category, confidence, reasoning}` for the pipeline to persist.
"""

from __future__ import annotations

import httpx
from jinja2 import Environment, StrictUndefined

from ..clients import LoadedClient
from ..logging import get_logger
from ..scrapers.base import ScrapedMedia, ScrapedPost, ScrapedStory
from .media_sampler import pick_for_ai
from .providers.gemini import ClassifyResult, MediaBlob, classify_with_gemini
from .providers.openai import classify_with_openai

log = get_logger(__name__)

# Fail loudly if a prompt template references a variable we don't provide —
# better than silently rendering an empty string.
_JINJA = Environment(undefined=StrictUndefined, autoescape=False)


def classify(
    *,
    post: ScrapedPost,
    loaded_client: LoadedClient,
    blobs: list[MediaBlob] | None = None,
) -> ClassifyResult | None:
    """Return a classification or None if AI is disabled / unusable for this post.

    `blobs`: pre-fetched media bytes. Ingest passes None (media is fetched from
    the still-fresh CDN source_url); retry jobs pass storage-sourced blobs
    because the CDN URLs have long expired by the time a retry fires.
    """
    provider = loaded_client.config.ai.provider
    if not loaded_client.prompt_template.strip():
        log.info("ai.skip.no_prompt", client=loaded_client.slug)
        return None

    prompt = _render_prompt(loaded_client, post)
    if blobs is None:
        sample = pick_for_ai(post)
        blobs = _fetch_media_blobs(sample)
    categories = [c.name for c in loaded_client.categories]

    if provider == "openai":
        return classify_with_openai(prompt=prompt, media=blobs, categories=categories)

    # Gemini-first with OpenAI fallback.
    try:
        return classify_with_gemini(prompt=prompt, media=blobs, categories=categories)
    except Exception as exc:
        log.warning("ai.gemini.failed_falling_back_to_openai", error=str(exc))
        return classify_with_openai(prompt=prompt, media=blobs, categories=categories)


def classify_story(
    *,
    story: ScrapedStory,
    loaded_client: LoadedClient,
) -> ClassifyResult | None:
    """Classify a story using the same per-client prompt as posts."""
    provider = loaded_client.config.ai.provider
    if not loaded_client.prompt_template.strip():
        log.info("ai.skip.no_prompt", client=loaded_client.slug)
        return None

    prompt = _render_prompt_for_story(loaded_client, story)
    blobs = _fetch_media_blobs(story.media)
    categories = [c.name for c in loaded_client.categories]

    if provider == "openai":
        return classify_with_openai(prompt=prompt, media=blobs, categories=categories)

    try:
        return classify_with_gemini(prompt=prompt, media=blobs, categories=categories)
    except Exception as exc:
        log.warning("ai.gemini.failed_falling_back_to_openai", error=str(exc))
        return classify_with_openai(prompt=prompt, media=blobs, categories=categories)


# =========================
# Internals
# =========================


def _render_prompt(loaded_client: LoadedClient, post: ScrapedPost) -> str:
    template = _JINJA.from_string(loaded_client.prompt_template)
    categories_block = "\n".join(
        f"- {c.name}: {c.description}" if c.description else f"- {c.name}"
        for c in loaded_client.categories
    )
    return template.render(
        categories=categories_block,
        caption=post.caption or "",
        post_type=post.post_type,
        permalink=post.permalink or "",
        client_name=loaded_client.name,
    )


def _render_prompt_for_story(loaded_client: LoadedClient, story: ScrapedStory) -> str:
    template = _JINJA.from_string(loaded_client.prompt_template)
    categories_block = "\n".join(
        f"- {c.name}: {c.description}" if c.description else f"- {c.name}"
        for c in loaded_client.categories
    )
    return template.render(
        categories=categories_block,
        caption=story.caption or "",
        post_type="story",
        permalink="",
        client_name=loaded_client.name,
    )


def _fetch_media_blobs(media: list[ScrapedMedia]) -> list[MediaBlob]:
    blobs: list[MediaBlob] = []
    if not media:
        return blobs

    with httpx.Client(
        timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True
    ) as http:
        for item in media:
            try:
                resp = http.get(item.source_url)
                resp.raise_for_status()
                mime = resp.headers.get("content-type") or _fallback_mime(item.media_type)
                blobs.append(MediaBlob(bytes_data=resp.content, mime_type=mime))
            except Exception as exc:
                # Media download failing for AI is non-fatal — classify on what we have.
                log.warning(
                    "ai.media.fetch_failed", url=item.source_url, error=str(exc)
                )
    return blobs


def _fallback_mime(media_type: str) -> str:
    return "video/mp4" if media_type == "video" else "image/jpeg"
