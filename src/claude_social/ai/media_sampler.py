"""
Decide which media to send to the AI.

Rules:
- Single image / single video / Reel  → send the one media item.
- Carousel with ≤3 slides             → send all.
- Carousel with >3 slides             → send first + middle + last.

This keeps AI cost predictable even for 10-slide carousels while still
capturing the visual variation across the post.
"""

from __future__ import annotations

from ..scrapers.base import ScrapedMedia, ScrapedPost


def pick_for_ai(post: ScrapedPost) -> list[ScrapedMedia]:
    media = [m for m in post.media if m.source_url]
    if not media:
        return []
    if post.post_type == "carousel" and len(media) > 3:
        return [media[0], media[len(media) // 2], media[-1]]
    return media
