"""
TikTok scraper - single Apify tier.

Posts come from `clockworks/tiktok-profile-scraper` with the video/cover
download add-on enabled, so `mediaUrls` (and `videoMeta.downloadAddr`) point
at Apify key-value-store copies instead of short-lived TikTok CDN URLs.
Stories come from `igview-owner/tiktok-story-viewer`, whose dataset mixes
real story items with `status: "no_stories"` sentinel records that must be
filtered out.

An EnsembleData primary tier is deferred; normalizers stay module-level pure
functions (same layout as instagram.py) so a second tier can reuse them later.

Actor output shapes are loose, so every field read goes through `.get(...)`
and the full raw item is preserved on the post/story row. TikTok also serves
silently-degraded data at times (items with an id but no engagement counts at
all); those are logged and still emitted with None metrics rather than dropped.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from apify_client import ApifyClient

from ..config import get_settings
from ..logging import get_logger
from .base import (
    REEL_COVER_SLIDE_INDEX,
    ScrapedMedia,
    ScrapedPost,
    ScrapedStory,
    dedupe_reel_cover,
    parse_ts,
)

log = get_logger(__name__)

# Engagement fields checked by the degradation guard. All-absent on an item
# that still has an id means TikTok served a silently-degraded payload.
_METRIC_KEYS = ("diggCount", "commentCount", "playCount", "shareCount")


class TikTokScraper:
    platform = "tiktok"

    def __init__(self) -> None:
        s = get_settings()
        self._client = ApifyClient(s.apify_token)
        self._actor = s.apify_tiktok_actor
        self._story_actor = s.apify_tiktok_story_actor
        # Set after each scrape_* call when the platform-side numeric user id
        # is resolved; the pipeline persists it to skip lookups next run.
        self.discovered_platform_account_id: str | None = None

    # -------------------------
    # Posts
    # -------------------------

    def scrape_posts(
        self,
        handle: str,
        limit: int | None = None,
        since: str | None = None,
        until: str | None = None,
        platform_account_id: str | None = None,
    ) -> list[ScrapedPost]:
        """
        Args:
            since: ISO date string - only return posts on or after this date.
            until: ISO date string - upper date bound, mapped to the actor's
                `newestPostDate`. The actor's schema words it as "published
                before [date]", so the boundary day may be EXCLUSIVE (unlike
                the inclusive IG contract) - unverified against a real run.
                Both filters use the actor's date add-on (paid, but cheaper
                than over-fetching and filtering locally).
        """
        self.discovered_platform_account_id = platform_account_id
        actor_input: dict[str, Any] = {
            "profiles": [handle.lstrip("@")],
            "resultsPerPage": limit or 30,
            "shouldDownloadVideos": True,
            "shouldDownloadCovers": True,
            "shouldDownloadSlideshowImages": True,
            "excludePinnedPosts": False,
        }
        if since:
            actor_input["oldestPostDateUnified"] = since
        if until:
            actor_input["newestPostDate"] = until

        # Zero raw items is a valid empty scrape, not an error - the pipeline
        # monitors empty-scrape rates separately.
        items = self._run_actor(self._actor, actor_input, kind="run", handle=handle)

        posts: list[ScrapedPost] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            if not raw.get("id"):
                log.warning(
                    "tiktok.post.missing_id",
                    handle=handle,
                    web_video_url=raw.get("webVideoUrl"),
                )
                continue
            if not self.discovered_platform_account_id:
                author_id = (raw.get("authorMeta") or {}).get("id")
                if author_id:
                    self.discovered_platform_account_id = str(author_id)
            try:
                posts.append(_normalize_post(raw))
            except Exception as exc:
                log.warning(
                    "tiktok.post.normalize_failed",
                    error=str(exc),
                    platform_post_id=raw.get("id"),
                )
        return posts

    # -------------------------
    # Stories
    # -------------------------

    def scrape_stories(
        self,
        handle: str,
        platform_account_id: str | None = None,
    ) -> list[ScrapedStory]:
        """Fetch active TikTok stories for one profile.

        Empty list = no active stories right now (NOT an error). The actor
        emits a sentinel record (`status: "no_stories"`) instead of an empty
        dataset for storyless accounts; sentinels are filtered here.
        """
        self.discovered_platform_account_id = platform_account_id
        actor_input: dict[str, Any] = {"uniqueIds": [handle.lstrip("@")]}

        items = self._run_actor(
            self._story_actor, actor_input, kind="stories", handle=handle
        )

        stories: list[ScrapedStory] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            story_id = raw.get("video_id") or raw.get("aweme_id")
            if not story_id:
                # No story id = not a story. The routine "no active stories"
                # sentinel is silent; anything else id-less is logged so a
                # dataset-shape change can't silently drop real items.
                if raw.get("status") != "no_stories":
                    log.warning(
                        "tiktok.story.unrecognized_item",
                        handle=handle,
                        keys=sorted(raw),
                    )
                continue
            author_id = (raw.get("author_info") or {}).get("id")
            if author_id:
                self.discovered_platform_account_id = str(author_id)
            try:
                stories.append(_normalize_story(raw))
            except Exception as exc:
                log.warning(
                    "tiktok.story.normalize_failed",
                    error=str(exc),
                    platform_story_id=story_id,
                )
        return stories

    def _run_actor(
        self,
        actor: str,
        actor_input: dict[str, Any],
        *,
        kind: str,
        handle: str,
    ) -> list[dict[str, Any]]:
        """Call an Apify actor and collect its dataset items."""
        log.info(f"tiktok.{kind}.start", actor=actor, handle=handle)
        run = self._client.actor(actor).call(run_input=actor_input)
        if not run:
            log.error(f"tiktok.{kind}.no_run_returned", handle=handle)
            return []
        items = list(self._client.dataset(run["defaultDatasetId"]).iterate_items())
        log.info(f"tiktok.{kind}.finished", handle=handle, items=len(items))
        return items


# =========================
# Normalizers (pure functions - reusable by a future EnsembleData tier)
# =========================


def _post_media(raw: dict[str, Any]) -> list[ScrapedMedia]:
    """Media list for one post item. Slideshow -> one image per mediaUrls
    entry. Video -> mp4 at slide 0 (mediaUrls first, downloadAddr fallback)
    plus the cover at REEL_COVER_SLIDE_INDEX when present."""
    media_urls = [u for u in (raw.get("mediaUrls") or []) if u]
    video_meta = raw.get("videoMeta") or {}

    if raw.get("isSlideshow"):
        if not media_urls:
            # Download add-on failed/unavailable: the post row would persist
            # with zero media forever (ingest never backfills existing posts).
            log.warning(
                "tiktok.post.no_slideshow_images", platform_post_id=raw.get("id")
            )
        return [
            ScrapedMedia(slide_index=i, media_type="image", source_url=url)
            for i, url in enumerate(media_urls)
        ]

    media: list[ScrapedMedia] = []
    video_url = media_urls[0] if media_urls else (video_meta.get("downloadAddr") or "")
    if video_url:
        media.append(
            ScrapedMedia(
                slide_index=0,
                media_type="video",
                source_url=video_url,
                duration_seconds=video_meta.get("duration"),
                width=video_meta.get("width"),
                height=video_meta.get("height"),
            )
        )
    else:
        log.warning(
            "tiktok.post.no_video_url",
            platform_post_id=raw.get("id"),
        )
    cover_url = video_meta.get("coverUrl")
    if cover_url:
        media.append(
            ScrapedMedia(
                slide_index=REEL_COVER_SLIDE_INDEX,
                media_type="image",
                source_url=cover_url,
                width=video_meta.get("width"),
                height=video_meta.get("height"),
            )
        )
    return media


def _normalize_post(raw: dict[str, Any]) -> ScrapedPost:
    platform_post_id = raw.get("id") or ""
    if not platform_post_id:
        raise ValueError("post has no id - cannot dedupe")

    if all(raw.get(k) is None for k in _METRIC_KEYS):
        # TikTok served a silently-degraded item: id present, engagement
        # counts entirely absent. Emit the post anyway (metrics None).
        log.warning("tiktok.degraded_item", platform_post_id=platform_post_id)

    posted_at = parse_ts(raw.get("createTimeISO")) or parse_ts(raw.get("createTime"))
    play_count = raw.get("playCount")

    return ScrapedPost(
        platform="tiktok",
        platform_post_id=str(platform_post_id),
        post_type="carousel" if raw.get("isSlideshow") else "video",
        caption=raw.get("text"),
        permalink=raw.get("webVideoUrl"),
        posted_at=posted_at,
        media=dedupe_reel_cover(_post_media(raw)),
        like_count=raw.get("diggCount"),
        comment_count=raw.get("commentCount"),
        # TikTok exposes a single play counter; mirror it into both fields.
        view_count=play_count,
        play_count=play_count,
        save_count=raw.get("collectCount"),
        share_count=raw.get("shareCount"),
        raw=raw,
    )


def _normalize_story(raw: dict[str, Any]) -> ScrapedStory:
    platform_story_id = str(raw.get("video_id") or raw.get("aweme_id") or "")
    if not platform_story_id:
        raise ValueError("story has no video_id/aweme_id")

    posted_at = parse_ts(raw.get("create_time")) or parse_ts(raw.get("create_time_date"))
    # TikTok stories expire 24h after posting; the actor returns no expiry field.
    expires_at = posted_at + timedelta(hours=24) if posted_at else None

    video_url = raw.get("video_url")
    if video_url:
        media = [
            ScrapedMedia(
                slide_index=0,
                media_type="video",
                source_url=video_url,
                duration_seconds=raw.get("duration"),
            )
        ]
    else:
        media = [
            ScrapedMedia(
                slide_index=0,
                media_type="image",
                source_url=raw.get("cover_url") or "",
            )
        ]

    return ScrapedStory(
        platform="tiktok",
        platform_story_id=platform_story_id,
        posted_at=posted_at,
        expires_at=expires_at,
        caption=raw.get("title") or None,
        media=media,
        raw=raw,
    )
