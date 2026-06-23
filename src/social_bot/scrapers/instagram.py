"""
Instagram scraper — three-tier post fetching.

Posts tiering (top to bottom):
  1. HikerAPI (`api.instagrapi.com`) — managed mobile-private-API SaaS.
     Auth-first by construction, handles restricted-but-public profiles
     that the anonymous Apify actor can't see. Active only when
     `HIKER_API_KEY` is set; on transient/fatal error we fall through.
  2. `apify/instagram-scraper` — anonymous, cheap, public profiles only.
  3. `get-leads/all-in-one-instagram-scraper` — authenticated Apify with
     cookies + IPRoyal residential proxy. Tried only if (2) returns 0
     items AND `INSTAGRAM_COOKIES` is set.

The two Apify actors' output shapes are loose (they evolve), so we code
defensively: every field read goes through `.get(...)` and we lean on the
`raw` dict to preserve anything we didn't map yet.

Stories scraping mirrors the post tiering:
  1. HikerAPI `/v1/user/stories/by/id` (when configured). Auth-first, so
     restricted-but-public accounts work.
  2. `igview-owner/instagram-story-viewer` Apify actor — anonymous, public-
     only. Fallthrough on hiker error.

When the caller passes a cached `platform_account_id` (the IG `pk`), we
skip the per-run username→pk lookup, halving HikerAPI request cost on
the stories cron.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apify_client import ApifyClient

from ..config import get_settings
from ..logging import get_logger
from ._hiker_client import HikerClient, HikerFatal, HikerTransient
from .base import REEL_COVER_SLIDE_INDEX, ScrapedMedia, ScrapedPost, ScrapedStory

log = get_logger(__name__)

# Items the fallback actor emits in its dataset alongside profile records.
# Filtered out so they don't get treated as post data.
_FALLBACK_NON_PROFILE_RESULT_TYPES = frozenset(
    {"quality_report", "bandwidth_report", "input_validation_error", "info"}
)


class InstagramScraper:
    platform = "instagram"

    def __init__(self) -> None:
        s = get_settings()
        self._client = ApifyClient(s.apify_token)
        self._actor = s.apify_instagram_actor
        self._fallback_actor = s.apify_instagram_fallback_actor
        # Primary + optional backup cookies for the fallback actor. Cookies are
        # raw JSON strings (the actor accepts that format directly). Each cookie
        # has its own admission-gate quota in the actor (keyed by cookieHash),
        # so the backup is a hot spare: try primary first, fall through to
        # backup on admission-gate denial or cookie-expired errors.
        self._cookies_primary: str | None = s.instagram_cookies
        self._cookie_country_primary: str = s.instagram_cookie_country
        self._cookies_backup: str | None = s.instagram_cookies_backup
        self._cookie_country_backup: str = s.instagram_cookie_country_backup
        self._residential_proxy_url: str | None = s.residential_proxy_url
        # HikerAPI top tier. None = not configured → graceful degradation to
        # the existing Apify-only flow.
        self._hiker: HikerClient | None = (
            HikerClient(s.hiker_api_key) if s.hiker_api_key else None
        )
        # Set after each scrape_* call when we successfully resolve the
        # platform-side user ID (Instagram pk). The pipeline reads this and
        # persists it on the account row so future runs skip the lookup.
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
            since: ISO date string (e.g. "2026-04-27") — only return posts on or after this date.
            until: ISO date string (e.g. "2026-05-03") — only return posts on or before this date.
            platform_account_id: cached IG `pk` for this handle. When set,
                the HikerAPI tier skips the username→pk lookup (saves one
                paid request per run).
        """
        self.discovered_platform_account_id = platform_account_id
        # Tier 1: HikerAPI (top tier, if configured). Trust an empty success
        # — falling through to Apify on an empty-but-valid response would
        # waste paid calls AND, while Apify free-tier is exhausted, propagate
        # ApifyApiError up through the per-account loop and skip downstream
        # accounts in the same cron run. Only fall through on hiker errors.
        if self._hiker is not None:
            try:
                return self._scrape_posts_hiker(
                    handle,
                    limit=limit,
                    since=since,
                    until=until,
                    user_id=platform_account_id,
                )
            except (HikerTransient, HikerFatal) as exc:
                log.warning(
                    "hiker.failed_falling_through",
                    handle=handle,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

        # Tier 2: Apify primary (anonymous, public-only).
        posts, raw_item_count = self._scrape_posts_primary(
            handle, limit=limit, since=since, until=until
        )
        # Gate fallback on the primary actor's raw item count, not on normalized
        # posts — otherwise a normalizer bug would silently trigger a paid
        # fallback run even though the primary actor delivered data.
        if raw_item_count > 0:
            return posts
        if not self._cookies_primary:
            log.info("apify.fallback.skipped_no_cookies", handle=handle)
            return posts

        # Tier 3: Apify cookies+proxy fallback.
        log.info("apify.fallback.triggered", handle=handle, primary_count=0)
        return self._scrape_posts_fallback(handle, limit=limit, since=since, until=until)

    def _scrape_posts_hiker(
        self,
        handle: str,
        limit: int | None,
        since: str | None,
        until: str | None,
        user_id: str | None,
    ) -> list[ScrapedPost]:
        """Fetch posts via HikerAPI. Returns normalized list; may raise Hiker* exceptions."""
        assert self._hiker is not None  # caller guards on this
        since_dt = _parse_iso_date(since)
        until_dt = _parse_iso_date(until)
        log.info(
            "hiker.scrape.start",
            handle=handle,
            limit=limit,
            cached_user_id=bool(user_id),
        )
        # Resolve the pk in the scraper (not inside the client) so we can
        # capture it for caching even when fetch_user_medias would have
        # done the lookup internally.
        if not user_id:
            user_id = self._hiker.lookup_user_id(handle)
        self.discovered_platform_account_id = user_id
        raw_items = self._hiker.fetch_user_medias(
            handle,
            limit=limit or 30,
            since_dt=since_dt,
            until_dt=until_dt,
            user_id=user_id,
        )
        log.info("hiker.scrape.finished", handle=handle, items=len(raw_items))

        posts: list[ScrapedPost] = []
        for raw in raw_items:
            try:
                posts.append(_normalize_post_hiker(raw))
            except Exception as exc:
                log.warning(
                    "hiker.post.normalize_failed",
                    error=str(exc),
                    platform_post_id=raw.get("code") or raw.get("pk"),
                )

        return posts

    def _scrape_posts_primary(
        self,
        handle: str,
        limit: int | None,
        since: str | None,
        until: str | None,
    ) -> tuple[list[ScrapedPost], int]:
        """Returns (normalized posts, raw item count from the actor dataset)."""
        profile_url = _profile_url(handle)
        actor_input: dict[str, Any] = {
            "directUrls": [profile_url],
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
            return [], 0

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
        return posts, len(items)

    def _scrape_posts_fallback(
        self,
        handle: str,
        limit: int | None,
        since: str | None,
        until: str | None,
    ) -> list[ScrapedPost]:
        posts, gate_denied = self._call_fallback_actor(
            handle, limit, since, until,
            cookies=self._cookies_primary,
            cookie_country=self._cookie_country_primary,
            cookie_label="primary",
        )
        if posts:
            return posts
        if not gate_denied:
            # No admission-gate error — primary cookie just didn't find the
            # account. Backup cookie won't help (same account-level visibility).
            return posts
        if not self._cookies_backup:
            log.info("apify.fallback.no_backup_cookie", handle=handle)
            return posts
        log.info("apify.fallback.retry_backup_cookie", handle=handle)
        posts, _ = self._call_fallback_actor(
            handle, limit, since, until,
            cookies=self._cookies_backup,
            cookie_country=self._cookie_country_backup,
            cookie_label="backup",
        )
        return posts

    def _call_fallback_actor(
        self,
        handle: str,
        limit: int | None,
        since: str | None,
        until: str | None,
        *,
        cookies: str | None,
        cookie_country: str,
        cookie_label: str,
    ) -> tuple[list[ScrapedPost], bool]:
        """Returns (posts, gate_denied). gate_denied=True signals the caller
        to retry with the backup cookie (admission-gate is per-cookie)."""
        actor_input: dict[str, Any] = {
            "scrapeMode": "instagram-profile-scraper",
            "profiles": [handle],
            "maxPostsPerProfile": min(limit or 30, 100),
            "loginCookies": cookies,
            "cookieCountry": cookie_country,
        }

        if self._residential_proxy_url:
            # External residential proxy (e.g. IPRoyal) — the country must
            # already be encoded in the URL (e.g. IPRoyal puts it in the
            # password as `pass_country-ie`). Passed to the actor as a custom
            # proxy URL; Apify's plan restrictions don't apply because the
            # proxy host isn't proxy.apify.com.
            actor_input["proxyTier"] = "custom"
            actor_input["proxyConfiguration"] = {
                "proxyUrls": [self._residential_proxy_url]
            }
            proxy_label = f"residential-{cookie_country}"
        else:
            actor_input["proxyTier"] = "none"
            proxy_label = "none"

        log.info(
            "apify.fallback.start",
            actor=self._fallback_actor,
            handle=handle,
            cookie=cookie_label,
            proxy=proxy_label,
        )
        run = self._client.actor(self._fallback_actor).call(run_input=actor_input)
        if not run:
            log.error("apify.fallback.no_run_returned", handle=handle, cookie=cookie_label)
            return [], False

        dataset_id = run["defaultDatasetId"]
        items = list(self._client.dataset(dataset_id).iterate_items())

        profile_items: list[dict[str, Any]] = []
        gate_errors: list[dict[str, Any]] = []
        for it in items:
            rt = it.get("resultType")
            if rt == "input_validation_error":
                gate_errors.append(it)
            elif rt not in _FALLBACK_NON_PROFILE_RESULT_TYPES and not it.get("_message"):
                profile_items.append(it)

        if gate_errors:
            for err in gate_errors:
                log.warning(
                    "apify.fallback.admission_gate",
                    handle=handle,
                    cookie=cookie_label,
                    errors=err.get("errors"),
                )
            return [], True

        log.info(
            "apify.fallback.finished",
            handle=handle,
            cookie=cookie_label,
            profiles=len(profile_items),
        )

        # Pre-parse the window bounds once — the inner loop runs once per post.
        since_dt = _parse_iso_date(since)
        until_dt = _parse_iso_date(until)

        posts: list[ScrapedPost] = []
        seen_ids: set[str] = set()
        for profile in profile_items:
            # Iterate both latestPosts and latestReels — reels are a separate
            # array in this actor's profile mode, and IG's posts tab includes
            # reels too, so dedupe by platform_post_id to be safe.
            combined = (profile.get("latestPosts") or []) + (profile.get("latestReels") or [])
            for raw_post in combined:
                post_id = raw_post.get("postId") or raw_post.get("shortCode") or ""
                if post_id and post_id in seen_ids:
                    continue
                posted_at = _parse_ts(raw_post.get("timestamp"))
                if _ts_outside_window(posted_at, since=since_dt, until=until_dt):
                    continue
                try:
                    normalized = _normalize_post_fallback(raw_post, posted_at=posted_at)
                    if normalized.post_type == "carousel":
                        log.info(
                            "apify.fallback.carousel_single_slide",
                            post_id=normalized.platform_post_id,
                        )
                    posts.append(normalized)
                    if post_id:
                        seen_ids.add(post_id)
                except Exception as exc:
                    log.warning(
                        "apify.fallback.post.normalize_failed",
                        error=str(exc),
                        platform_post_id=raw_post.get("postId") or raw_post.get("shortCode"),
                    )
        log.info(
            "apify.fallback.normalized",
            handle=handle,
            cookie=cookie_label,
            posts=len(posts),
        )
        return posts, False

    # -------------------------
    # Stories
    # -------------------------

    def scrape_stories(
        self,
        handle: str,
        platform_account_id: str | None = None,
    ) -> list[ScrapedStory]:
        """Fetch active stories for one IG profile.

        Tier 1: HikerAPI (when configured). Auth-first, sees restricted
        profiles. Skips the pk lookup if `platform_account_id` is cached.
        Tier 2: igview Apify actor (anonymous, public-only).

        Empty list = no active stories right now (NOT an error). Hiker
        errors fall through to Apify; a clean empty hiker response does not.
        """
        self.discovered_platform_account_id = platform_account_id

        if self._hiker is not None:
            try:
                return self._scrape_stories_hiker(
                    handle, user_id=platform_account_id
                )
            except (HikerTransient, HikerFatal) as exc:
                log.warning(
                    "hiker.stories.failed_falling_through",
                    handle=handle,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

        return self._scrape_stories_apify(handle)

    def _scrape_stories_hiker(
        self,
        handle: str,
        user_id: str | None,
    ) -> list[ScrapedStory]:
        assert self._hiker is not None
        cached = user_id is not None
        if not user_id:
            # HikerAPI intermittently 404s UserNotFound for valid accounts; retry
            # once here so the stories cron doesn't fall through to paid Apify on
            # a transient miss.
            user_id = self._hiker.lookup_user_id(handle, retry_on_404=True)
        self.discovered_platform_account_id = user_id

        log.info("hiker.stories.start", handle=handle, cached_user_id=cached)
        raw_items = self._hiker.fetch_user_stories(user_id=user_id)
        log.info("hiker.stories.finished", handle=handle, items=len(raw_items))

        stories: list[ScrapedStory] = []
        for raw in raw_items:
            try:
                stories.append(_normalize_story_hiker(raw))
            except Exception as exc:
                log.warning(
                    "hiker.story.normalize_failed",
                    error=str(exc),
                    platform_story_id=raw.get("pk") or raw.get("id"),
                )
        return stories

    def _scrape_stories_apify(self, handle: str) -> list[ScrapedStory]:
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
        return datetime.fromtimestamp(value, tz=UTC)
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


def _media_from_child(child: dict[str, Any], slide_index: int) -> list[ScrapedMedia]:
    """Build media entries from an Apify carousel child. Videos return
    [video, cover_image] so the cover is downloaded at scrape time."""
    is_video = bool(child.get("videoUrl") or (child.get("type") or "").lower() == "video")
    if not is_video:
        return [
            ScrapedMedia(
                slide_index=slide_index,
                media_type="image",
                source_url=child.get("displayUrl") or "",
                width=child.get("dimensionsWidth"),
                height=child.get("dimensionsHeight"),
            )
        ]

    items: list[ScrapedMedia] = [
        ScrapedMedia(
            slide_index=slide_index,
            media_type="video",
            source_url=child.get("videoUrl") or "",
            duration_seconds=child.get("videoDuration"),
            width=child.get("dimensionsWidth"),
            height=child.get("dimensionsHeight"),
        )
    ]
    cover = child.get("displayUrl")
    if cover:
        items.append(
            ScrapedMedia(
                slide_index=REEL_COVER_SLIDE_INDEX,
                media_type="image",
                source_url=cover,
                width=child.get("dimensionsWidth"),
                height=child.get("dimensionsHeight"),
            )
        )
    return items


def _normalize_post(raw: dict[str, Any]) -> ScrapedPost:
    post_type = _determine_post_type(raw)
    children = raw.get("childPosts") or []
    media: list[ScrapedMedia] = []

    if post_type == "carousel" and children:
        for idx, child in enumerate(children):
            media.extend(_media_from_child(child, idx))
    else:
        # Single-media post (image, video, or reel).
        is_video = post_type in {"video", "reel"} or bool(raw.get("videoUrl"))
        if is_video:
            media.append(
                ScrapedMedia(
                    slide_index=0,
                    media_type="video",
                    source_url=raw.get("videoUrl") or "",
                    duration_seconds=raw.get("videoDuration"),
                    width=raw.get("dimensionsWidth"),
                    height=raw.get("dimensionsHeight"),
                )
            )
            cover = raw.get("displayUrl")
            if cover:
                # Pair the reel/video with its cover thumbnail — downloaded at
                # scrape time so the report doesn't have to chase stale URLs.
                media.append(
                    ScrapedMedia(
                        slide_index=REEL_COVER_SLIDE_INDEX,
                        media_type="image",
                        source_url=cover,
                        width=raw.get("dimensionsWidth"),
                        height=raw.get("dimensionsHeight"),
                    )
                )
        else:
            media.append(
                ScrapedMedia(
                    slide_index=0,
                    media_type="image",
                    source_url=raw.get("displayUrl") or "",
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


def _parse_iso_date(value: str | None) -> datetime | None:
    """Parse an ISO date string for window comparisons. Returns None if absent or invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _ts_outside_window(
    ts: datetime | None,
    *,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    # Unknown timestamps are treated as in-window: the caller has already
    # decided this is a candidate post; dropping it for a parse failure
    # would be a silent data loss.
    if ts is None:
        return False
    if since is not None and ts < since:
        return True
    return until is not None and ts > until


def _normalize_post_fallback(
    raw: dict[str, Any],
    *,
    posted_at: datetime | None,
) -> ScrapedPost:
    """Normalize a post from `get-leads/all-in-one-instagram-scraper`'s profile mode."""
    # TODO: latestPosts items don't include carousel children — for
    # Sidecar/Carousel posts we capture only the cover frame. If we need
    # full slides on the fallback path, add a follow-up call via
    # `scrapeMode: instagram-post-scraper` keyed on shortCode.
    platform_post_id = (
        raw.get("postId") or raw.get("shortCode") or raw.get("shortcode") or ""
    )
    if not platform_post_id:
        raise ValueError("post has no postId / shortCode — cannot dedupe")

    media_type_raw = (raw.get("mediaType") or "").lower()
    if media_type_raw in {"sidecar", "carousel", "carousel_album"}:
        post_type = "carousel"
    elif media_type_raw == "video" or raw.get("videoUrl"):
        post_type = "reel" if (raw.get("videoPlayCount") or raw.get("videoViewCount")) else "video"
    else:
        post_type = "image"

    is_video = post_type in {"video", "reel"} or bool(raw.get("videoUrl"))
    source = raw.get("videoUrl") or raw.get("displayUrl") or ""
    dims = raw.get("dimensions") or {}
    media = [
        ScrapedMedia(
            slide_index=0,
            media_type="video" if is_video else "image",
            source_url=source,
            duration_seconds=raw.get("videoDuration"),
            width=dims.get("width"),
            height=dims.get("height"),
        )
    ]

    return ScrapedPost(
        platform="instagram",
        platform_post_id=str(platform_post_id),
        post_type=post_type,
        caption=raw.get("caption"),
        permalink=raw.get("url"),
        posted_at=posted_at,
        media=media,
        like_count=raw.get("likesCount"),
        comment_count=raw.get("commentsCount"),
        view_count=raw.get("videoViewCount"),
        play_count=raw.get("videoPlayCount"),
        raw=raw,
    )


def _normalize_post_hiker(raw: dict[str, Any]) -> ScrapedPost:
    """Normalize a media dict from HikerAPI's /v2/user/medias response.

    Field conventions follow instagrapi's mobile-private-API output:
      media_type: 1=image, 2=video/reel, 8=carousel
      product_type: 'clips' (reel) | 'feed' (video) | 'carousel_container'
      caption: nested {text, ...} — top-level `caption_text` is None on /v2
      taken_at: Unix epoch seconds
    """
    code = raw.get("code") or ""
    pk = raw.get("pk") or ""
    if not pk:
        raise ValueError("media has no pk — cannot dedupe")
    if not code:
        raise ValueError("media has no code — cannot build permalink")

    media_type = raw.get("media_type")
    product_type = (raw.get("product_type") or "").lower()

    if media_type == 8 or product_type == "carousel_container":
        post_type = "carousel"
    elif media_type == 2:
        post_type = "reel" if product_type == "clips" else "video"
    else:
        post_type = "image"

    if post_type == "carousel":
        children = raw.get("carousel_media") or []
        media = [m for idx, c in enumerate(children) for m in _hiker_media_from_item(c, idx)]
        if not media:
            # Carousel with no children — happens occasionally. Fall back to
            # the cover image so downstream pipeline still has something.
            media = _hiker_media_from_item(raw, 0)
    else:
        media = _hiker_media_from_item(raw, 0)

    caption_obj = raw.get("caption")
    caption = caption_obj.get("text") if isinstance(caption_obj, dict) else None

    return ScrapedPost(
        platform="instagram",
        platform_post_id=str(pk),
        post_type=post_type,
        caption=caption,
        permalink=f"https://www.instagram.com/p/{code}/",
        posted_at=_parse_ts(raw.get("taken_at")),
        media=media,
        like_count=raw.get("like_count"),
        comment_count=raw.get("comment_count"),
        view_count=raw.get("view_count") or raw.get("play_count"),
        play_count=raw.get("play_count"),
        raw=raw,
    )


def _hiker_cover_url(raw: dict[str, Any]) -> str:
    """Best-available cover/thumbnail URL from a HikerAPI media payload."""
    image_versions2 = raw.get("image_versions2") or {}
    candidates = image_versions2.get("candidates") or []
    if candidates and isinstance(candidates[0], dict):
        url = candidates[0].get("url")
        if url:
            return url
    return raw.get("thumbnail_url") or ""


def _hiker_media_from_item(raw: dict[str, Any], slide_index: int) -> list[ScrapedMedia]:
    """Build ScrapedMedia entries from a top-level media or a carousel child.

    Image: returns [image].
    Video/reel: returns [video, cover_image]. The cover is stored at the
    sentinel REEL_COVER_SLIDE_INDEX so it doesn't collide with carousel slides
    and so reports can find it by convention. Storing cover at scrape-time
    avoids the stale-URL heal cascade — fresh URLs work immediately, week-old
    ones don't.

    Same field shape either way — IG's mobile API uses the same Media model
    nested under `carousel_media[]`.
    """
    is_video = raw.get("media_type") == 2

    if not is_video:
        return [
            ScrapedMedia(
                slide_index=slide_index,
                media_type="image",
                source_url=_hiker_cover_url(raw),
                width=raw.get("original_width"),
                height=raw.get("original_height"),
            )
        ]

    video_versions = raw.get("video_versions") or []
    video_url = ""
    if video_versions and isinstance(video_versions[0], dict):
        video_url = video_versions[0].get("url") or ""
    if not video_url:
        video_url = raw.get("video_url") or ""

    items: list[ScrapedMedia] = [
        ScrapedMedia(
            slide_index=slide_index,
            media_type="video",
            source_url=video_url,
            duration_seconds=raw.get("video_duration"),
            width=raw.get("original_width"),
            height=raw.get("original_height"),
        )
    ]
    cover_url = _hiker_cover_url(raw)
    if cover_url:
        items.append(
            ScrapedMedia(
                slide_index=REEL_COVER_SLIDE_INDEX,
                media_type="image",
                source_url=cover_url,
                width=raw.get("original_width"),
                height=raw.get("original_height"),
            )
        )
    return items


def _normalize_story_hiker(raw: dict[str, Any]) -> ScrapedStory:
    """Normalize a HikerAPI /v1/user/stories story item.

    Field conventions (instagrapi v1):
      pk / id: story media id
      media_type: 1=image, 2=video
      taken_at: epoch seconds
      expiring_at: epoch seconds
      video_url: top-level for v1 (no `video_versions` array)
      thumbnail_url: image fallback
    """
    platform_story_id = str(raw.get("pk") or raw.get("id") or "")
    if not platform_story_id:
        raise ValueError("story has no pk/id")

    is_video = raw.get("media_type") == 2
    if is_video:
        source = raw.get("video_url") or ""
        if not source:
            video_versions = raw.get("video_versions") or []
            if video_versions and isinstance(video_versions[0], dict):
                source = video_versions[0].get("url") or ""
    else:
        source = raw.get("thumbnail_url") or ""
        if not source:
            image_versions2 = raw.get("image_versions2") or {}
            candidates = image_versions2.get("candidates") or []
            if candidates and isinstance(candidates[0], dict):
                source = candidates[0].get("url") or ""

    media = [
        ScrapedMedia(
            slide_index=0,
            media_type="video" if is_video else "image",
            source_url=source,
            duration_seconds=raw.get("video_duration") if is_video else None,
            width=raw.get("original_width"),
            height=raw.get("original_height"),
        )
    ]

    posted_at = _parse_ts(raw.get("taken_at"))
    expires_at = _parse_ts(raw.get("expiring_at"))
    if expires_at is None and posted_at is not None:
        expires_at = posted_at + timedelta(hours=24)

    caption_obj = raw.get("caption")
    caption = caption_obj.get("text") if isinstance(caption_obj, dict) else None

    return ScrapedStory(
        platform="instagram",
        platform_story_id=platform_story_id,
        posted_at=posted_at,
        expires_at=expires_at,
        caption=caption,
        media=media,
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
