"""
Scraper protocol and normalized data shapes.

Every platform scraper returns the same shapes so the pipeline is
platform-agnostic. Adding a new platform means implementing this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class ScrapedMedia:
    slide_index: int
    media_type: str               # 'image' | 'video'
    source_url: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None


@dataclass(slots=True)
class ScrapedPost:
    platform: str
    platform_post_id: str
    post_type: str                # 'image' | 'carousel' | 'reel' | 'video'
    caption: str | None
    permalink: str | None
    posted_at: datetime | None
    media: list[ScrapedMedia] = field(default_factory=list)
    # Metrics snapshot at scrape time — whatever the platform exposes.
    like_count: int | None = None
    comment_count: int | None = None
    view_count: int | None = None
    play_count: int | None = None
    save_count: int | None = None
    share_count: int | None = None
    # Full raw item from the scraper, stored on the post row for re-derivation.
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScrapedStory:
    platform: str
    platform_story_id: str
    posted_at: datetime | None
    expires_at: datetime | None
    caption: str | None
    media: list[ScrapedMedia] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class Scraper(Protocol):
    """All platform scrapers conform to this."""

    platform: str

    def scrape_posts(
        self,
        handle: str,
        limit: int | None = None,
        since: str | None = None,
        until: str | None = None,
        platform_account_id: str | None = None,
    ) -> list[ScrapedPost]: ...

    def scrape_stories(
        self,
        handle: str,
        platform_account_id: str | None = None,
    ) -> list[ScrapedStory]: ...

    # Set after each scrape_* call when the scraper resolves the platform's
    # internal user ID. Pipelines persist it to skip the lookup next run.
    discovered_platform_account_id: str | None
