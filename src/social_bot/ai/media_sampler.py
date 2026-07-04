"""
Decide which media to send to the AI — and fetch the bytes when they live in
Supabase Storage.

Sampling rules (single source of truth; classify, describe, and retry jobs
all route through here):
- Sentinel reel covers (slide_index=99) are dropped when any real media
  exists — the cover is a keyframe of the video already being sent, so
  including it pays for a redundant image on every reel call.
- ≤3 items → send all.
- >3 items → send first + middle + last.

This keeps AI cost predictable even for 10-slide carousels while still
capturing the visual variation across the post.
"""

from __future__ import annotations

from collections.abc import Callable

from ..logging import get_logger
from ..scrapers.base import REEL_COVER_SLIDE_INDEX, ScrapedMedia, ScrapedPost
from ..storage import media as storage_media
from .providers.gemini import MediaBlob

log = get_logger(__name__)


def sample_media[T](items: list[T], get_slide: Callable[[T], int | None]) -> list[T]:
    """Apply the sampling rules to any media representation (ScrapedMedia or
    DB row dicts), given a slide_index accessor."""
    real = [i for i in items if get_slide(i) != REEL_COVER_SLIDE_INDEX]
    # Keep the cover only when it's all we have (e.g. video URL missing).
    items = real or items
    if len(items) > 3:
        return [items[0], items[len(items) // 2], items[-1]]
    return items


def pick_for_ai(post: ScrapedPost) -> list[ScrapedMedia]:
    media = [m for m in post.media if m.source_url]
    return sample_media(media, lambda m: m.slide_index)


def fetch_storage_blobs(media_rows: list[dict], item_ref: str) -> list[MediaBlob]:
    """Sample media rows, then download each survivor's bytes from Supabase
    Storage (CDN source_urls expire; storage paths don't). A row without a
    storage_path or a failed download is logged and skipped — AI runs on
    whatever media survived."""
    sampled = sample_media(media_rows, lambda r: r.get("slide_index"))
    blobs: list[MediaBlob] = []
    for row in sampled:
        path = row.get("storage_path")
        if not path:
            log.warning(
                "ai.media.no_storage_path",
                item=item_ref, slide=row.get("slide_index"),
            )
            continue
        try:
            data, mime = storage_media.download_from_storage(path)
            blobs.append(MediaBlob(bytes_data=data, mime_type=mime))
        except Exception as exc:
            log.warning(
                "ai.media.storage_download_failed",
                item=item_ref, path=path, error=str(exc),
            )
    return blobs
