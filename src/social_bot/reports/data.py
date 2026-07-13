"""Supabase fetch + bucketing for reports.

Single entry point: `load_report_data(client_slug, period)` returns a
`ReportData` tree the renderer + synthesis can consume without ever talking
to Supabase again.

Key behaviour:
- Reel hero images are stored at scrape time (slide_index=99 sentinel for
  "auxiliary cover, not a real IG slide") — see scrapers/instagram.py. For
  legacy reels scraped before that change, `_heal_reel_cover` mines the URL
  from posts.raw_payload, uploads to Storage, and inserts the media row.
  Defense-in-depth only; should fire on almost nothing post-2026-05-29.
- Posts bucketed by ai_category, OrderedDict sorted by count desc — leads
  with the biggest theme in every rendered slide.
- total_posts counts non-reels only; total_reels counts reels (for TikTok,
  regular videos count as reels — see `_is_reel`). They sum to the grand
  total shown on the Overview "Posts" circle.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..clients import load_client
from ..db.client import get_supabase, rows
from ..db.queries import insert_media
from ..logging import get_logger
from ..scrapers.base import REEL_COVER_SLIDE_INDEX
from ..storage.media import build_storage_path, download_and_upload, download_from_storage

log = get_logger(__name__)

DEFAULT_CACHE_DIR = Path("/tmp/report_images")


# ─────────────────────────────────────────────────────────────────────
# Domain types
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Period:
    start: datetime              # inclusive, tz-aware UTC
    end: datetime                # inclusive
    label: str                   # rendered on Cover, e.g. "25 April – 25 May 2026"


@dataclass
class PostRow:
    id: str                      # posts.id (uuid)
    platform_post_id: str
    posted_at: datetime
    post_type: str               # 'image' | 'carousel' | 'reel' | 'video'
    caption: str | None
    ai_category: str | None
    ai_description: str | None
    like_count: int
    comment_count: int
    hero_image_path: Path | None

    @property
    def engagement(self) -> tuple[int, int]:
        """Ranking key for picking the strongest post: total interactions,
        then likes as the tie-breaker. Single source of truth for every
        'highest-engagement' selection across the report pipeline."""
        return (self.like_count + self.comment_count, self.like_count)


@dataclass
class StoryRow:
    id: str
    posted_at: datetime
    ai_category: str | None
    ai_description: str | None
    hero_image_path: Path | None


@dataclass
class CategoryPreviewRow:
    name: str
    image_path: Path
    post_count: int


@dataclass
class AccountData:
    handle: str
    platform: str
    account_id: str
    posts_by_category: OrderedDict[str, list[PostRow]]   # sorted by count desc
    stories_by_category: OrderedDict[str, list[StoryRow]]
    intro_previews: list[CategoryPreviewRow]               # capped at 4
    total_posts: int             # non-reel count (see _is_reel; tiktok videos count as reels)
    total_reels: int             # reel-equivalent count (_is_reel)
    total_stories: int
    total_likes: int
    total_comments: int


@dataclass
class ReportData:
    client_slug: str
    client_name: str
    period: Period
    accounts: list[AccountData]  # ordered as in client.yaml; inactive filtered

    @property
    def grand_total_posts(self) -> int:
        return sum(a.total_posts + a.total_reels for a in self.accounts)


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────

def load_report_data(
    client_slug: str,
    period: Period,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    include_inactive: bool = False,
    platform: str | None = None,
) -> ReportData:
    cache_dir.mkdir(parents=True, exist_ok=True)

    # client.yaml is the source of truth for which accounts are active in a
    # report; the accounts table's is_active flag can drift.
    loaded = load_client(client_slug)
    wanted = (
        loaded.config.accounts if include_inactive else loaded.active_accounts
    )
    # Optional single-platform report (e.g. a standalone Facebook deck).
    if platform is not None:
        wanted = [a for a in wanted if a.platform == platform]

    client = _fetch_client(client_slug)
    accounts_meta = _fetch_accounts(client["id"])

    # The same handle can exist on multiple platforms (e.g. agapeslovensko on
    # both instagram and facebook), so accounts are keyed by the (platform,
    # handle) natural key — never by handle alone, which collides. Resolution
    # happens once here; everything downstream uses account_id.
    meta_by_key = {(m["platform"], m["handle"]): m for m in accounts_meta}
    accounts: list[AccountData] = []
    for acct in wanted:  # preserve the order declared in client.yaml
        meta = meta_by_key.get((acct.platform, acct.handle))
        if not meta:
            log.warning(
                "report.account_missing_in_db",
                client=client_slug, platform=acct.platform, handle=acct.handle,
            )
            continue
        accounts.append(_build_account_data(meta, period, cache_dir, client_slug))

    return ReportData(
        client_slug=client_slug,
        client_name=loaded.name,
        period=period,
        accounts=accounts,
    )


def build_period(start: datetime, end: datetime) -> Period:
    """Build a Period with an en-dash date label (not em-dash)."""
    same_year = start.year == end.year
    same_month = same_year and start.month == end.month
    if same_month:
        label = f"{start.day}–{end.day} {end.strftime('%B %Y')}"
    elif same_year:
        label = (
            f"{start.day} {start.strftime('%B')} – "
            f"{end.day} {end.strftime('%B %Y')}"
        )
    else:
        label = (
            f"{start.day} {start.strftime('%B %Y')} – "
            f"{end.day} {end.strftime('%B %Y')}"
        )
    return Period(start=start, end=end, label=label)


# ─────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────

def _fetch_client(slug: str) -> dict:
    sb = get_supabase()
    res = sb.table("clients").select("id, name, slug").eq("slug", slug).limit(1).execute()
    if not res.data:
        raise ValueError(f"Client not found: {slug}")
    return rows(res)[0]


def _fetch_accounts(client_id: str) -> list[dict]:
    """Return all account rows for a client.

    A client has only a handful of accounts, so we fetch them all in one
    round-trip and match on the (platform, handle) natural key in Python,
    rather than building a tuple-IN filter PostgREST handles awkwardly.
    """
    sb = get_supabase()
    res = (
        sb.table("accounts")
        .select("id, handle, platform, is_active")
        .eq("client_id", client_id)
        .execute()
    )
    return rows(res)


def _is_reel(platform: str, post_type: str) -> bool:
    """Reel-equivalence for the Overview tile split. TikTok has no 'reel'
    post_type — its regular videos ARE the reel format, so they count here
    (otherwise the Reels circle reads 0 on every TikTok account). TikTok
    slideshows stay post_type 'carousel' and land in total_posts.

    Keep in lockstep with `reel_term` below: whatever this counts, that
    labels."""
    return post_type == "reel" or (platform == "tiktok" and post_type == "video")


def reel_term(platform: str) -> str:
    """Platform terminology for the short-video count of `_is_reel` (plural,
    lowercase). 'Reels' is Instagram/Facebook jargon; TikTok posts are just
    videos. Lives next to _is_reel so the count and its label can't drift."""
    return "videos" if platform == "tiktok" else "reels"


def _build_account_data(
    meta: dict, period: Period, cache_dir: Path, client_slug: str,
) -> AccountData:
    handle = meta["handle"]
    platform = meta["platform"]
    account_id = meta["id"]

    post_rows_raw = _fetch_posts(account_id, period)
    story_rows_raw = _fetch_stories(account_id, period)

    post_ids = [r["id"] for r in post_rows_raw]
    story_ids = [r["id"] for r in story_rows_raw]

    metrics = _fetch_latest_metrics(post_ids)
    post_media = _fetch_post_media(post_ids)
    story_media = _fetch_story_media(story_ids)

    posts: list[PostRow] = []
    for r in post_rows_raw:
        m = metrics.get(r["id"], {})
        hero = _resolve_post_hero(
            r, post_media.get(r["id"], []), cache_dir, handle, client_slug, platform,
        )
        posts.append(PostRow(
            id=r["id"],
            platform_post_id=r["platform_post_id"],
            posted_at=_parse_dt(r["posted_at"]),
            post_type=r.get("post_type") or "image",
            caption=r.get("caption"),
            ai_category=r.get("ai_category"),
            ai_description=r.get("ai_description"),
            like_count=m.get("like_count") or 0,
            comment_count=m.get("comment_count") or 0,
            hero_image_path=hero,
        ))

    stories: list[StoryRow] = []
    for r in story_rows_raw:
        hero = _resolve_story_hero(story_media.get(r["id"], []), cache_dir)
        stories.append(StoryRow(
            id=r["id"],
            posted_at=_parse_dt(r["posted_at"]),
            ai_category=r.get("ai_category"),
            ai_description=r.get("ai_description"),
            hero_image_path=hero,
        ))

    posts_by_category = _bucket_posts(posts)
    stories_by_category = _bucket_stories(stories)
    intro_previews = _pick_intro_previews(posts_by_category)
    total_reels = sum(1 for p in posts if _is_reel(platform, p.post_type))

    return AccountData(
        handle=handle,
        platform=platform,
        account_id=account_id,
        posts_by_category=posts_by_category,
        stories_by_category=stories_by_category,
        intro_previews=intro_previews,
        total_posts=len(posts) - total_reels,
        total_reels=total_reels,
        total_stories=len(stories),
        total_likes=sum(p.like_count for p in posts),
        total_comments=sum(p.comment_count for p in posts),
    )


def _fetch_posts(account_id: str, period: Period) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("posts")
        .select(
            "id, platform_post_id, posted_at, post_type, caption, "
            "ai_category, ai_description, raw_payload"
        )
        .eq("account_id", account_id)
        .gte("posted_at", period.start.isoformat())
        .lte("posted_at", period.end.isoformat())
        .order("posted_at")
        .execute()
    )
    return rows(res)


def _fetch_stories(account_id: str, period: Period) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("stories")
        .select("id, posted_at, ai_category, ai_description")
        .eq("account_id", account_id)
        .gte("posted_at", period.start.isoformat())
        .lte("posted_at", period.end.isoformat())
        .order("posted_at")
        .execute()
    )
    return rows(res)


def _fetch_latest_metrics(post_ids: list[str]) -> dict[str, dict]:
    """Latest snapshot per post via a single .in_() query.

    Supabase's PostgREST doesn't expose DISTINCT ON; we fetch all snapshots
    in one round-trip and reduce client-side. Cheap for monthly reports.
    """
    if not post_ids:
        return {}
    sb = get_supabase()
    out: dict[str, dict] = {}
    # Chunk to keep URLs sane.
    for chunk in _chunks(post_ids, 100):
        res = (
            sb.table("post_metrics")
            .select("post_id, like_count, comment_count, scraped_at")
            .in_("post_id", chunk)
            .order("scraped_at", desc=True)
            .execute()
        )
        for row in rows(res):
            pid = row["post_id"]
            if pid not in out:
                out[pid] = {
                    "like_count": row.get("like_count"),
                    "comment_count": row.get("comment_count"),
                }
    return out


def _fetch_post_media(post_ids: list[str]) -> dict[str, list[dict]]:
    if not post_ids:
        return {}
    sb = get_supabase()
    out: dict[str, list[dict]] = {}
    for chunk in _chunks(post_ids, 100):
        res = (
            sb.table("media")
            .select("post_id, slide_index, media_type, storage_path")
            .in_("post_id", chunk)
            .execute()
        )
        for row in rows(res):
            out.setdefault(row["post_id"], []).append(row)
    return out


def _fetch_story_media(story_ids: list[str]) -> dict[str, list[dict]]:
    if not story_ids:
        return {}
    sb = get_supabase()
    out: dict[str, list[dict]] = {}
    for chunk in _chunks(story_ids, 100):
        res = (
            sb.table("story_media")
            .select("story_id, media_type, storage_path")
            .in_("story_id", chunk)
            .execute()
        )
        for row in rows(res):
            out.setdefault(row["story_id"], []).append(row)
    return out


# ─────────────────────────────────────────────────────────────────────
# Hero image resolution + reel cover self-healing
# ─────────────────────────────────────────────────────────────────────

def _resolve_post_hero(
    post_row: dict,
    media_rows: list[dict],
    cache_dir: Path,
    handle: str,
    client_slug: str,
    platform: str,
) -> Path | None:
    """Pick an image to represent this post; download to cache.

    Order:
    1. Existing media row with media_type='image', lowest slide_index.
    2. If post is an Instagram video/reel only: self-heal — fetch cover from
       raw_payload, upload to Supabase Storage as a new media row
       (slide_index=99), then return that path.
    3. Give up and return None.
    """
    images = [m for m in media_rows if m.get("media_type") == "image"]
    if images:
        images.sort(key=lambda m: m.get("slide_index") or 0)
        storage_path = images[0].get("storage_path")
        if storage_path:
            return _download_storage_to_cache(storage_path, cache_dir)

    # No image in storage. Healing mines IG-shaped raw_payload and writes an
    # instagram/... storage path, so it only applies to Instagram. Facebook
    # stores reel covers at scrape time, so a missing FB cover just means no
    # hero (the renderer falls back accordingly).
    if platform != "instagram":
        return None
    return _heal_reel_cover(post_row, handle, client_slug, cache_dir)


def _resolve_story_hero(media_rows: list[dict], cache_dir: Path) -> Path | None:
    images = [m for m in media_rows if m.get("media_type") == "image"]
    if not images:
        return None
    storage_path = images[0].get("storage_path")
    if not storage_path:
        return None
    return _download_storage_to_cache(storage_path, cache_dir)


def _heal_reel_cover(
    post_row: dict, handle: str, client_slug: str, cache_dir: Path,
) -> Path | None:
    """Pull reel cover JPG from raw_payload, upload to Supabase, insert media row.

    Idempotent: subsequent calls find the inserted image row and skip this path.
    IG signed URLs may have expired for very old reels; in that case returns None
    and the renderer falls back to no image for that post.
    """
    raw = post_row.get("raw_payload") or {}
    url = _extract_cover_url(raw)
    if not url:
        return None

    post_id = post_row["id"]
    posted_at = _parse_dt(post_row["posted_at"])
    platform_post_id = post_row["platform_post_id"]

    storage_path = build_storage_path(
        client_slug=client_slug,
        account_handle=handle,
        platform="instagram",
        post_id=post_id,
        slide_index=REEL_COVER_SLIDE_INDEX,
        media_type="image",
        source_url=url,
        posted_at=posted_at,
    )

    try:
        uploaded = download_and_upload(source_url=url, storage_path=storage_path)
    except Exception as exc:
        log.warning(
            "reel_cover.heal_failed",
            post_id=post_id,
            platform_post_id=platform_post_id,
            error=str(exc),
        )
        return None

    insert_media(
        post_id=post_id,
        slide_index=REEL_COVER_SLIDE_INDEX,
        media_type="image",
        source_url=url,
        storage_path=uploaded.storage_path,
        bytes_size=uploaded.bytes_size,
    )
    log.info("reel_cover.healed", post_id=post_id, storage_path=uploaded.storage_path)

    return _download_storage_to_cache(uploaded.storage_path, cache_dir)


def _extract_cover_url(raw: dict) -> str | None:
    """Find a cover image URL inside a HikerAPI/Apify post raw_payload."""
    # HikerAPI shape — preferred
    iv = raw.get("image_versions2") or {}
    cands = iv.get("candidates") or []
    if cands and isinstance(cands[0], dict):
        url = cands[0].get("url")
        if url:
            return url
    # HikerAPI top-level thumbnail
    if raw.get("thumbnail_url"):
        return raw["thumbnail_url"]
    # Apify shape (camelCase)
    for key in ("displayUrl", "thumbnailUrl", "thumbnailSrc"):
        if raw.get(key):
            return raw[key]
    return None


def _download_storage_to_cache(storage_path: str, cache_dir: Path) -> Path:
    """Download an object from Supabase Storage to a local cache file.

    Cache key = the storage_path itself (sanitized). Idempotent — skip if cached.
    """
    safe = storage_path.replace("/", "_")
    local = cache_dir / safe
    if local.exists() and local.stat().st_size > 0:
        return local
    data, _mime = download_from_storage(storage_path)
    local.write_bytes(data)
    return local


# ─────────────────────────────────────────────────────────────────────
# Bucketing + previews
# ─────────────────────────────────────────────────────────────────────

UNCATEGORIZED = "(Uncategorized)"

def _bucket_by_category[T](
    items: list[T],
    get_cat: Callable[[T], str | None],
    get_dt: Callable[[T], datetime],
) -> OrderedDict[str, list[T]]:
    """Group by ai_category, sort categories by count desc, items by date asc."""
    raw: dict[str, list[T]] = {}
    for it in items:
        raw.setdefault(get_cat(it) or UNCATEGORIZED, []).append(it)
    ordered: OrderedDict[str, list[T]] = OrderedDict()
    for cat in sorted(raw, key=lambda c: (-len(raw[c]), c)):
        ordered[cat] = sorted(raw[cat], key=get_dt)
    return ordered


def _bucket_posts(posts: list[PostRow]) -> OrderedDict[str, list[PostRow]]:
    return _bucket_by_category(posts, lambda p: p.ai_category, lambda p: p.posted_at)


def _bucket_stories(stories: list[StoryRow]) -> OrderedDict[str, list[StoryRow]]:
    return _bucket_by_category(stories, lambda s: s.ai_category, lambda s: s.posted_at)


def _pick_intro_previews(
    posts_by_category: OrderedDict[str, list[PostRow]],
    *,
    max_previews: int = 4,
) -> list[CategoryPreviewRow]:
    """One image per category, picked as the highest-engagement post with a
    hero image. Capped at the layout's 4 slots."""
    previews: list[CategoryPreviewRow] = []
    for cat, plist in posts_by_category.items():
        if len(previews) >= max_previews:
            break
        with_image = [p for p in plist if p.hero_image_path is not None]
        if not with_image:
            continue
        top = max(with_image, key=lambda p: p.engagement)
        previews.append(CategoryPreviewRow(
            name=cat,
            image_path=top.hero_image_path,  # type: ignore[arg-type]
            post_count=len(plist),
        ))
    return previews


# ─────────────────────────────────────────────────────────────────────
# Small utilities
# ─────────────────────────────────────────────────────────────────────

def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    # Supabase returns ISO strings; tolerate trailing Z.
    s = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
