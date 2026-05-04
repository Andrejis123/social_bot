"""
Instagram scraper — wraps the Apify `apify/instagram-scraper` actor.

The actor's output shape is somewhat loose (Apify actors evolve), so we code
defensively: every field read goes through `.get(...)` and we lean on the
`raw` dict to preserve anything we didn't map yet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apify_client import ApifyClient

from ..config import get_settings
from ..logging import get_logger
from .base import ScrapedMedia, ScrapedPost, ScrapedStory

log = get_logger(__name__)


class InstagramScraper:
    platform = "instagram"

    def __init__(self) -> None:
        s = get_settings()
        self._client = ApifyClient(s.apify_token)
        self._actor = s.apify_instagram_actor

    # -------------------------
    # Posts
    # -------------------------

    def scrape_posts(
        self,
        handle: str,
        limit: int | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[ScrapedPost]:
        """Run the actor for one profile and normalize each item.

        Args:
            since: ISO date string (e.g. "2026-04-27") — only return posts on or after this date.
            until: ISO date string (e.g. "2026-05-03") — only return posts on or before this date.
        """
        actor_input: dict[str, Any] = {
            "usernames": [handle],
            "resultsType": "posts",
            "resultsLimit": limit or 30,
            "addParentData": False,
        }
        if since:
            actor_input["onlyPostsNewerThan"] = since
        if until:
            actor_input["onlyPostsOlderThan"] = until

        log.info("apify.run.start", actor=self._actor, handle=handle, limit=limit)
        run = self._client.actor(self._actor).call(run_input=actor_input)
        if not run:
            log.error("apify.run.no_run_returned", handle=handle)
            return []

        dataset_id = run["defaultDatasetId"]
        items = list(self._client.dataset(dataset_id).iterate_items())
        log.info("apify.run.finished", handle=handle, items=len(items))

        posts: list[ScrapedPost] = []
        for raw in items:
            try:
                posts.append(_normalize_post(raw))
            except Exception as exc:
                log.warning(
                    "apify.post.normalize_failed",
                    error=str(exc),
                    platform_post_id=raw.get("id") or raw.get("shortCode"),
                )
        return posts

    # -------------------------
    # Stories
    # -------------------------

    def scrape_stories(self, handle: str) -> list[ScrapedStory]:
        """Run igview-owner/instagram-story-viewer for one profile."""
        actor = "igview-owner/instagram-story-viewer"
        actor_input: dict[str, Any] = {"usernames": [handle]}

        log.info("apify.stories.start", actor=actor, handle=handle)
        run = self._client.actor(actor).call(run_input=actor_input)
        if not run:
            log.error("apify.stories.no_run_returned", handle=handle)
            return []

        dataset_id = run["defaultDatasetId"]
        items = list(self._client.dataset(dataset_id).iterate_items())
        log.info("apify.stories.finished", handle=handle, items=len(items))

        stories: list[ScrapedStory] = []
        for raw in items:
            try:
                stories.append(_normalize_story(raw))
            except Exception as exc:
                log.warning(
                    "apify.story.normalize_failed",
                    error=str(exc),
                    platform_story_id=raw.get("id"),
                )
        return stories


# =========================
# Normalizers (pure functions — easy to unit test)
# =========================


def _profile_url(handle: str) -> str:
    return f"https://www.instagram.com/{handle.lstrip('@')}/"


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    # Apify typically returns ISO-8601 strings.
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        # Unix seconds.
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _determine_post_type(raw: dict[str, Any]) -> str:
    product_type = (raw.get("productType") or "").lower()
    t = (raw.get("type") or "").lower()
    if product_type == "clips":
        return "reel"
    if t in {"sidecar", "carousel"} or raw.get("childPosts"):
        return "carousel"
    if t == "video":
        return "video"
    return "image"


def _media_from_child(child: dict[str, Any], slide_index: int) -> ScrapedMedia:
    is_video = bool(child.get("videoUrl") or (child.get("type") or "").lower() == "video")
    source = child.get("videoUrl") or child.get("displayUrl") or ""
    return ScrapedMedia(
        slide_index=slide_index,
        media_type="video" if is_video else "image",
        source_url=source,
        duration_seconds=child.get("videoDuration"),
        width=child.get("dimensionsWidth"),
        height=child.get("dimensionsHeight"),
    )


def _normalize_post(raw: dict[str, Any]) -> ScrapedPost:
    post_type = _determine_post_type(raw)
    children = raw.get("childPosts") or []
    media: list[ScrapedMedia] = []

    if post_type == "carousel" and children:
        for idx, child in enumerate(children):
            media.append(_media_from_child(child, idx))
    else:
        # Single-media post (image, video, or reel). Build one ScrapedMedia.
        is_video = post_type in {"video", "reel"} or bool(raw.get("videoUrl"))
        source = raw.get("videoUrl") or raw.get("displayUrl") or ""
        media.append(
            ScrapedMedia(
                slide_index=0,
                media_type="video" if is_video else "image",
                source_url=source,
                duration_seconds=raw.get("videoDuration"),
                width=raw.get("dimensionsWidth"),
                height=raw.get("dimensionsHeight"),
            )
        )

    platform_post_id = (
        raw.get("id") or raw.get("shortCode") or raw.get("shortcode") or ""
    )
    if not platform_post_id:
        raise ValueError("post has no id / shortCode — cannot dedupe")

    return ScrapedPost(
        platform="instagram",
        platform_post_id=str(platform_post_id),
        post_type=post_type,
        caption=raw.get("caption"),
        permalink=raw.get("url") or raw.get("permalink"),
        posted_at=_parse_ts(raw.get("timestamp") or raw.get("takenAt")),
        media=media,
        like_count=raw.get("likesCount"),
        comment_count=raw.get("commentsCount"),
        view_count=raw.get("videoViewCount") or raw.get("viewCount"),
        play_count=raw.get("videoPlayCount") or raw.get("playCount"),
        raw=raw,
    )


def _normalize_story(raw: dict[str, Any]) -> ScrapedStory:
    # igview-owner/instagram-story-viewer uses camelCase field names.
    platform_story_id = str(raw.get("storyId") or "")
    if not platform_story_id:
        raise ValueError("story has no id")

    is_video = bool(raw.get("videoUrl"))
    source = raw.get("videoUrl") or raw.get("imageUrl") or ""

    media = [
        ScrapedMedia(
            slide_index=0,
            media_type="video" if is_video else "image",
            source_url=source,
        )
    ]

    posted_at = _parse_ts(raw.get("takenAt"))
    # igview doesn't return expiring_at; Instagram stories always expire 24h after posting.
    expires_at = None
    if posted_at:
        from datetime import timedelta
        expires_at = posted_at + timedelta(hours=24)

    return ScrapedStory(
        platform="instagram",
        platform_story_id=platform_story_id,
        posted_at=posted_at,
        expires_at=expires_at,
        caption=raw.get("caption"),
        media=media,
        raw=raw,
    )
