"""
Facebook scraper — public Page posts via the official Apify actor.

Phase A (this module): anonymous post scraping of public Pages through
`apify/facebook-posts-scraper`. Verified 2026-06-23 that anonymous access
returns full month history with per-reaction counts and view counts for a
normal public Page (no cookies needed). The `get-leads` all-in-one actor's
anonymous mode is crippled (1 post), so we use the official actor here.

Anonymous captures expose only the cover image for videos/reels (no playable
mp4), so video posts normalize to a single cover `image` media item — the same
way Instagram reel covers are stored.

Phase B (deferred): restricted / age-gated Pages (alcohol/tobacco) and stories.
Those need a logged-in 18+ burner; whether the official actor can read them
with cookies is unverified — do not assume.

Like the Instagram actor, the output shape is loose, so every field read goes
through `.get(...)` and the full `raw` item is preserved on the post row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apify_client import ApifyClient

from ..config import get_settings
from ..logging import get_logger
from .base import ScrapedMedia, ScrapedPost, ScrapedStory

log = get_logger(__name__)


class FacebookScraper:
    platform = "facebook"

    def __init__(self) -> None:
        s = get_settings()
        self._client = ApifyClient(s.apify_token)
        self._actor = s.apify_facebook_actor
        self.discovered_platform_account_id: str | None = None

    def scrape_posts(
        self,
        handle: str,
        limit: int | None = None,
        since: str | None = None,
        until: str | None = None,
        platform_account_id: str | None = None,
    ) -> list[ScrapedPost]:
        self.discovered_platform_account_id = platform_account_id
        actor_input: dict[str, Any] = {
            "startUrls": [{"url": _profile_url(handle)}],
            "resultsLimit": limit or 30,
        }
        if since:
            actor_input["onlyPostsNewerThan"] = since
        if until:
            actor_input["onlyPostsOlderThan"] = until

        log.info("facebook.run.start", actor=self._actor, handle=handle, limit=limit)
        run = self._client.actor(self._actor).call(run_input=actor_input)
        if not run:
            log.error("facebook.run.no_run_returned", handle=handle)
            return []

        items = list(self._client.dataset(run["defaultDatasetId"]).iterate_items())
        log.info("facebook.run.finished", handle=handle, items=len(items))

        posts: list[ScrapedPost] = []
        for raw in items:
            if not isinstance(raw, dict) or not raw.get("postId"):
                continue  # skip the run-summary / non-post records
            # Cache the page's numeric id for future runs (parity with IG pk).
            if not self.discovered_platform_account_id:
                page_id = raw.get("facebookId")
                if page_id:
                    self.discovered_platform_account_id = str(page_id)
            try:
                posts.append(_normalize_post_facebook(raw))
            except Exception as exc:
                log.warning(
                    "facebook.post.normalize_failed",
                    error=str(exc),
                    platform_post_id=raw.get("postId"),
                )
        return posts

    def scrape_stories(
        self,
        handle: str,
        platform_account_id: str | None = None,
    ) -> list[ScrapedStory]:
        # Phase B: FB story scraping is deferred (weak/expensive tooling, needs
        # an authenticated session). Return empty so the pipeline no-ops.
        self.discovered_platform_account_id = platform_account_id
        log.info("facebook.stories.skipped_phase_b", handle=handle)
        return []


# =========================
# Normalizer + helpers
# =========================


def _normalize_post_facebook(item: dict[str, Any]) -> ScrapedPost:
    media = _extract_media(item)
    caption = (item.get("text") or "").strip() or None
    return ScrapedPost(
        platform="facebook",
        platform_post_id=str(item.get("postId") or ""),
        post_type=_classify_post_type(item, media),
        caption=caption,
        # topLevelUrl is the canonical numeric /posts/<id> permalink; `url` is a
        # /reel/ or pfbid link that is less stable.
        permalink=item.get("topLevelUrl") or item.get("url"),
        posted_at=_parse_fb_time(item.get("time")),
        media=media,
        # `likes` is the reaction TOTAL (sum of like/love/care/...). FB has no
        # saves; views only exist for videos.
        like_count=_coerce_int(item.get("likes")),
        comment_count=_coerce_int(item.get("comments")),
        view_count=_coerce_int(item.get("viewsCount")),
        play_count=None,
        save_count=None,
        share_count=_coerce_int(item.get("shares")),
        raw=item,
    )


def _extract_media(item: dict[str, Any]) -> list[ScrapedMedia]:
    """Map the raw media[] to cover/photo images, skipping junk elements.

    Carousels can carry a leading element with `__typename: None` and no URL,
    and there are edge types (e.g. ProfilePicAttachmentMedia) with no usable
    source — both are filtered out so they don't become empty media rows.
    """
    out: list[ScrapedMedia] = []
    for raw in item.get("media") or []:
        if not isinstance(raw, dict):
            continue
        src = _media_source_url(raw)
        if not src:
            continue
        out.append(
            ScrapedMedia(
                slide_index=len(out),
                media_type="image",  # anon FB exposes only photos / video covers
                source_url=src,
            )
        )
    return out


def _media_source_url(media: dict[str, Any]) -> str | None:
    typename = media.get("__typename")
    if typename == "Photo":
        return (media.get("photo_image") or {}).get("uri") or media.get("thumbnail")
    if typename == "Video":
        return (media.get("thumbnailImage") or {}).get("uri") or media.get("thumbnail")
    return None


def _classify_post_type(item: dict[str, Any], media: list[ScrapedMedia]) -> str:
    if item.get("isVideo"):
        return "reel" if "/reel/" in (item.get("url") or "") else "video"
    if len(media) > 1:
        return "carousel"
    if len(media) == 1:
        return "image"
    return "text"


def _parse_fb_time(value: Any) -> datetime | None:
    """The actor returns ISO-8601 with a trailing Z (e.g. 2026-06-22T18:16:22.000Z)."""
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _profile_url(handle: str) -> str:
    h = handle.strip()
    if h.startswith("http"):
        return h
    return f"https://www.facebook.com/{h.lstrip('@')}/"
