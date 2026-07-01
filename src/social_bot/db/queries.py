"""
Typed CRUD helpers for Supabase tables.

This is the *only* module that knows about column names. Pipeline code calls
these functions — if we ever swap Supabase for raw Postgres, only this file
changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import batched
from typing import Any

from ..logging import get_logger
from .client import get_supabase, rows, single

log = get_logger(__name__)


# =========================
# Clients & accounts
# =========================


def upsert_client(slug: str, name: str) -> str:
    """Insert or fetch a client row. Returns client id (uuid)."""
    sb = get_supabase()
    existing = sb.table("clients").select("id").eq("slug", slug).limit(1).execute()
    if existing.data:
        return rows(existing)[0]["id"]
    inserted = sb.table("clients").insert({"slug": slug, "name": name}).execute()
    return rows(inserted)[0]["id"]


def upsert_account(
    client_id: str,
    platform: str,
    handle: str,
    is_owned: bool = True,
) -> dict[str, Any]:
    """Insert or fetch an account row. Returns {'id', 'platform_account_id'}.

    platform_account_id is the platform's stable internal ID (e.g. IG `pk`).
    It's NULL until the first scrape discovers it; callers should persist via
    set_account_platform_id() to skip the per-run lookup afterwards.
    """
    sb = get_supabase()
    existing = (
        sb.table("accounts")
        .select("id, platform_account_id")
        .eq("platform", platform)
        .eq("handle", handle)
        .limit(1)
        .execute()
    )
    if existing.data:
        return rows(existing)[0]
    inserted = (
        sb.table("accounts")
        .insert(
            {
                "client_id": client_id,
                "platform": platform,
                "handle": handle,
                "is_owned": is_owned,
            }
        )
        .execute()
    )
    return {"id": rows(inserted)[0]["id"], "platform_account_id": None}


def set_account_platform_id(account_id: str, platform_account_id: str) -> None:
    """Cache the platform's internal user ID on an account row."""
    sb = get_supabase()
    sb.table("accounts").update(
        {"platform_account_id": platform_account_id}
    ).eq("id", account_id).execute()


# =========================
# Posts
# =========================


def find_post(platform: str, platform_post_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    res = (
        sb.table("posts")
        .select("id, ai_category")
        .eq("platform", platform)
        .eq("platform_post_id", platform_post_id)
        .limit(1)
        .execute()
    )
    matches = rows(res)
    return matches[0] if matches else None


def insert_post(
    *,
    account_id: str,
    platform: str,
    platform_post_id: str,
    post_type: str,
    caption: str | None,
    permalink: str | None,
    posted_at: datetime | None,
    raw_payload: dict[str, Any],
) -> str:
    sb = get_supabase()
    res = (
        sb.table("posts")
        .insert(
            {
                "account_id": account_id,
                "platform": platform,
                "platform_post_id": platform_post_id,
                "post_type": post_type,
                "caption": caption,
                "permalink": permalink,
                "posted_at": posted_at.isoformat() if posted_at else None,
                "raw_payload": raw_payload,
            }
        )
        .execute()
    )
    return rows(res)[0]["id"]


def get_account_with_client(account_id: str) -> dict[str, Any] | None:
    """Return account row joined with its client slug."""
    sb = get_supabase()
    res = (
        sb.table("accounts")
        .select("id, platform, handle, clients(slug)")
        .eq("id", account_id)
        .single()
        .execute()
    )
    row = single(res)
    if row is None:
        return None
    row["client_slug"] = (row.get("clients") or {}).get("slug")
    return row


def find_posts_needing_description(
    client_slug: str, max_attempts: int = 3, account_handle: str | None = None
) -> list[dict[str, Any]]:
    """Return classified posts that don't yet have a description, scoped to one client."""
    sb = get_supabase()
    client_row = sb.table("clients").select("id").eq("slug", client_slug).limit(1).execute()
    if not client_row.data:
        return []
    client_id = rows(client_row)[0]["id"]

    q = sb.table("accounts").select("id").eq("client_id", client_id)
    if account_handle:
        q = q.eq("handle", account_handle)
    account_rows = q.execute()
    account_ids = [a["id"] for a in rows(account_rows)]
    if not account_ids:
        return []

    res = (
        sb.table("posts")
        .select("id, platform_post_id, post_type, caption")
        .in_("account_id", account_ids)
        .not_.is_("ai_category", "null")
        .is_("ai_description", "null")
        .lt("ai_description_attempts", max_attempts)
        .order("first_seen_at", desc=False)
        .limit(100)
        .execute()
    )
    return rows(res)


def update_post_description(
    post_id: str,
    *,
    description: str,
    provider: str,
) -> None:
    sb = get_supabase()
    sb.table("posts").update(
        {
            "ai_description": description,
            "ai_description_at": datetime.utcnow().isoformat(),
            "ai_provider": provider,
        }
    ).eq("id", post_id).execute()


def increment_post_description_attempts(post_id: str, *, error: str) -> None:
    sb = get_supabase()
    current = sb.table("posts").select("ai_description_attempts").eq("id", post_id).single().execute()
    attempts = (single(current) or {}).get("ai_description_attempts", 0) + 1
    sb.table("posts").update(
        {
            "ai_description_attempts": attempts,
            "ai_description_error": error[:2000],
        }
    ).eq("id", post_id).execute()


def find_posts_needing_ai(max_attempts: int = 3) -> list[dict[str, Any]]:
    """Return posts that failed AI classification and haven't hit the attempt cap."""
    sb = get_supabase()
    res = (
        sb.table("posts")
        .select("id, platform, platform_post_id, post_type, caption, permalink, posted_at, account_id")
        .is_("ai_category", "null")
        .lt("ai_attempts", max_attempts)
        .order("first_seen_at", desc=False)
        .limit(100)
        .execute()
    )
    return rows(res)


def increment_post_ai_attempts(post_id: str, *, error: str) -> int:
    """Increment ai_attempts counter and store last error. Returns new attempt count."""
    sb = get_supabase()
    current = sb.table("posts").select("ai_attempts").eq("id", post_id).single().execute()
    attempts = (single(current) or {}).get("ai_attempts", 0) + 1
    sb.table("posts").update({
        "ai_attempts": attempts,
        "ai_last_error": error[:2000],
    }).eq("id", post_id).execute()
    return attempts


def update_post_ai(
    post_id: str,
    *,
    category: str,
    confidence: float | None,
    reasoning: str | None,
    prompt_version: str,
    provider: str,
) -> None:
    sb = get_supabase()
    sb.table("posts").update(
        {
            "ai_category": category,
            "ai_confidence": confidence,
            "ai_reasoning": reasoning,
            "ai_prompt_version": prompt_version,
            "ai_provider": provider,
            "ai_analyzed_at": datetime.utcnow().isoformat(),
        }
    ).eq("id", post_id).execute()


# =========================
# Metrics time-series
# =========================


def append_post_metrics(
    post_id: str,
    *,
    like_count: int | None = None,
    comment_count: int | None = None,
    view_count: int | None = None,
    play_count: int | None = None,
    save_count: int | None = None,
    share_count: int | None = None,
) -> None:
    sb = get_supabase()
    sb.table("post_metrics").insert(
        {
            "post_id": post_id,
            "like_count": like_count,
            "comment_count": comment_count,
            "view_count": view_count,
            "play_count": play_count,
            "save_count": save_count,
            "share_count": share_count,
        }
    ).execute()


# =========================
# Media
# =========================


def insert_media(
    *,
    post_id: str,
    slide_index: int,
    media_type: str,
    source_url: str | None,
    storage_path: str | None,
    duration_seconds: float | None = None,
    width: int | None = None,
    height: int | None = None,
    bytes_size: int | None = None,
) -> str:
    sb = get_supabase()
    res = (
        sb.table("media")
        .insert(
            {
                "post_id": post_id,
                "slide_index": slide_index,
                "media_type": media_type,
                "source_url": source_url,
                "storage_path": storage_path,
                "duration_seconds": duration_seconds,
                "width": width,
                "height": height,
                "bytes": bytes_size,
                "downloaded_at": datetime.utcnow().isoformat(),
            }
        )
        .execute()
    )
    return rows(res)[0]["id"]


def get_client_id_by_slug(slug: str) -> str | None:
    sb = get_supabase()
    res = sb.table("clients").select("id").eq("slug", slug).limit(1).execute()
    matches = rows(res)
    return matches[0]["id"] if matches else None


def list_accounts_for_client(client_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("accounts")
        .select("id, handle, platform")
        .eq("client_id", client_id)
        .execute()
    )
    return rows(res)


def list_posts_in_period(
    account_ids: list[str], start: datetime, end: datetime,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("posts")
        .select("id, account_id, posted_at, platform_post_id")
        .in_("account_id", account_ids)
        .gte("posted_at", start.isoformat())
        .lte("posted_at", end.isoformat())
        .execute()
    )
    return rows(res)


def list_media_for_posts(post_ids: list[str]) -> list[dict[str, Any]]:
    if not post_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("media")
        .select("post_id, slide_index, storage_path, media_type")
        .in_("post_id", post_ids)
        .not_.is_("storage_path", "null")
        .execute()
    )
    return rows(res)


def list_stories_in_period(
    account_ids: list[str], start: datetime, end: datetime,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("stories")
        .select("id, account_id, posted_at, platform_story_id")
        .in_("account_id", account_ids)
        .gte("posted_at", start.isoformat())
        .lte("posted_at", end.isoformat())
        .execute()
    )
    return rows(res)


def list_story_media_for_stories(story_ids: list[str]) -> list[dict[str, Any]]:
    if not story_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("story_media")
        .select("story_id, storage_path, media_type")
        .in_("story_id", story_ids)
        .not_.is_("storage_path", "null")
        .execute()
    )
    return rows(res)


def list_media_for_post(post_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("media")
        .select("*")
        .eq("post_id", post_id)
        .order("slide_index")
        .execute()
    )
    return rows(res)


# =========================
# Stories
# =========================


def find_story(platform: str, platform_story_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    res = (
        sb.table("stories")
        .select("id")
        .eq("platform", platform)
        .eq("platform_story_id", platform_story_id)
        .limit(1)
        .execute()
    )
    matches = rows(res)
    return matches[0] if matches else None


def insert_story(
    *,
    account_id: str,
    platform: str,
    platform_story_id: str,
    posted_at: datetime | None,
    expires_at: datetime | None,
    caption: str | None,
    raw_payload: dict[str, Any],
) -> str:
    sb = get_supabase()
    res = (
        sb.table("stories")
        .insert(
            {
                "account_id": account_id,
                "platform": platform,
                "platform_story_id": platform_story_id,
                "posted_at": posted_at.isoformat() if posted_at else None,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "caption": caption,
                "raw_payload": raw_payload,
            }
        )
        .execute()
    )
    return rows(res)[0]["id"]


def list_media_for_story(story_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("story_media")
        .select("*")
        .eq("story_id", story_id)
        .execute()
    )
    return rows(res)


def update_story_ai(
    story_id: str,
    *,
    category: str,
    confidence: float | None,
    reasoning: str | None,
    prompt_version: str,
    provider: str,
) -> None:
    sb = get_supabase()
    sb.table("stories").update(
        {
            "ai_category": category,
            "ai_confidence": confidence,
            "ai_reasoning": reasoning,
            "ai_prompt_version": prompt_version,
            "ai_provider": provider,
            "ai_analyzed_at": datetime.utcnow().isoformat(),
        }
    ).eq("id", story_id).execute()


def increment_story_ai_attempts(story_id: str, *, error: str) -> int:
    sb = get_supabase()
    current = sb.table("stories").select("ai_attempts").eq("id", story_id).single().execute()
    attempts = (single(current) or {}).get("ai_attempts", 0) + 1
    sb.table("stories").update({
        "ai_attempts": attempts,
        "ai_last_error": error[:2000],
    }).eq("id", story_id).execute()
    return attempts


def find_stories_needing_description(
    client_slug: str, max_attempts: int = 3, account_handle: str | None = None
) -> list[dict[str, Any]]:
    sb = get_supabase()
    client_row = sb.table("clients").select("id").eq("slug", client_slug).limit(1).execute()
    if not client_row.data:
        return []
    client_id = rows(client_row)[0]["id"]

    q = sb.table("accounts").select("id").eq("client_id", client_id)
    if account_handle:
        q = q.eq("handle", account_handle)
    account_rows = q.execute()
    account_ids = [a["id"] for a in rows(account_rows)]
    if not account_ids:
        return []

    res = (
        sb.table("stories")
        .select("id, platform_story_id, caption")
        .in_("account_id", account_ids)
        .not_.is_("ai_category", "null")
        .is_("ai_description", "null")
        .lt("ai_description_attempts", max_attempts)
        .order("first_seen_at", desc=False)
        .limit(200)
        .execute()
    )
    return rows(res)


def update_story_description(
    story_id: str,
    *,
    description: str,
    provider: str,
) -> None:
    sb = get_supabase()
    sb.table("stories").update(
        {
            "ai_description": description,
            "ai_description_at": datetime.utcnow().isoformat(),
            "ai_provider": provider,
        }
    ).eq("id", story_id).execute()


def increment_story_description_attempts(story_id: str, *, error: str) -> None:
    sb = get_supabase()
    current = sb.table("stories").select("ai_description_attempts").eq("id", story_id).single().execute()
    attempts = (single(current) or {}).get("ai_description_attempts", 0) + 1
    sb.table("stories").update(
        {
            "ai_description_attempts": attempts,
            "ai_description_error": error[:2000],
        }
    ).eq("id", story_id).execute()


def insert_story_media(
    *,
    story_id: str,
    media_type: str,
    source_url: str | None,
    storage_path: str | None,
    duration_seconds: float | None = None,
) -> None:
    sb = get_supabase()
    sb.table("story_media").insert(
        {
            "story_id": story_id,
            "media_type": media_type,
            "source_url": source_url,
            "storage_path": storage_path,
            "duration_seconds": duration_seconds,
            "downloaded_at": datetime.utcnow().isoformat(),
        }
    ).execute()


# =========================
# Drive sync
# =========================


def list_unsynced_post_media(account_ids: list[str], since: datetime) -> list[dict[str, Any]]:
    """Post media joined to posts: not yet synced to Drive, within the window, no reel covers."""
    if not account_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("media")
        .select(
            "id, slide_index, media_type, storage_path, "
            "posts!inner(id, account_id, platform_post_id, posted_at)"
        )
        .in_("posts.account_id", account_ids)
        .gte("posts.posted_at", since.isoformat())
        .is_("drive_synced_at", "null")
        .not_.is_("storage_path", "null")
        .neq("slide_index", 99)
        .execute()
    )
    out: list[dict[str, Any]] = []
    for r in rows(res):
        post: dict[str, Any] = r.get("posts") or {}
        out.append({
            "media_id": r["id"],
            "slide_index": r["slide_index"],
            "media_type": r["media_type"],
            "storage_path": r["storage_path"],
            "post_id": post.get("id"),
            "platform_post_id": post.get("platform_post_id"),
            "posted_at": post.get("posted_at"),
            "account_id": post.get("account_id"),
        })
    return out


def list_unsynced_story_media(account_ids: list[str], since: datetime) -> list[dict[str, Any]]:
    """Story media joined to stories: not yet synced to Drive, within the window."""
    if not account_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("story_media")
        .select(
            "id, media_type, storage_path, "
            "stories!inner(id, account_id, platform_story_id, posted_at)"
        )
        .in_("stories.account_id", account_ids)
        .gte("stories.posted_at", since.isoformat())
        .is_("drive_synced_at", "null")
        .not_.is_("storage_path", "null")
        .execute()
    )
    out: list[dict[str, Any]] = []
    for r in rows(res):
        story: dict[str, Any] = r.get("stories") or {}
        out.append({
            "story_media_id": r["id"],
            "media_type": r["media_type"],
            "storage_path": r["storage_path"],
            "story_id": story.get("id"),
            "platform_story_id": story.get("platform_story_id"),
            "posted_at": story.get("posted_at"),
            "account_id": story.get("account_id"),
        })
    return out


def mark_media_synced(media_id: str, drive_file_id: str) -> None:
    sb = get_supabase()
    sb.table("media").update({
        "drive_file_id": drive_file_id,
        "drive_synced_at": datetime.now(UTC).isoformat(),
    }).eq("id", media_id).execute()


def mark_story_media_synced(story_media_id: str, drive_file_id: str) -> None:
    sb = get_supabase()
    sb.table("story_media").update({
        "drive_file_id": drive_file_id,
        "drive_synced_at": datetime.now(UTC).isoformat(),
    }).eq("id", story_media_id).execute()


def list_expired_drive_media(cutoff: datetime) -> list[dict[str, Any]]:
    """Post media with Drive files whose post is older than cutoff (for retention prune)."""
    sb = get_supabase()
    res = (
        sb.table("media")
        .select("id, drive_file_id, posts!inner(posted_at)")
        .not_.is_("drive_synced_at", "null")
        .lt("posts.posted_at", cutoff.isoformat())
        .execute()
    )
    return [
        {"media_id": r["id"], "drive_file_id": r["drive_file_id"]}
        for r in rows(res)
    ]


def list_expired_drive_story_media(cutoff: datetime) -> list[dict[str, Any]]:
    """Story media with Drive files older than cutoff (for retention prune)."""
    sb = get_supabase()
    res = (
        sb.table("story_media")
        .select("id, drive_file_id, stories!inner(posted_at)")
        .not_.is_("drive_synced_at", "null")
        .lt("stories.posted_at", cutoff.isoformat())
        .execute()
    )
    return [
        {"story_media_id": r["id"], "drive_file_id": r["drive_file_id"]}
        for r in rows(res)
    ]


def clear_media_drive(media_id: str) -> None:
    sb = get_supabase()
    sb.table("media").update({
        "drive_file_id": None,
        "drive_synced_at": None,
    }).eq("id", media_id).execute()


def clear_story_media_drive(story_media_id: str) -> None:
    sb = get_supabase()
    sb.table("story_media").update({
        "drive_file_id": None,
        "drive_synced_at": None,
    }).eq("id", story_media_id).execute()


# =========================
# Archive ledger (Supabase Storage -> Drive bundle -> purge)
# =========================

_ARCHIVE_TABLES = ("media", "story_media")


def _update_archived_paths(
    payload: dict[str, Any], storage_paths: list[str], *, only_unarchived: bool
) -> int:
    """Apply `payload` to media+story_media rows matched by storage_path, in
    chunks. A path lives in exactly one table, so both are tried. Returns the
    total rows updated. `only_unarchived` adds the `archived_at IS NULL` guard."""
    sb = get_supabase()
    updated = 0
    for table in _ARCHIVE_TABLES:
        for chunk in batched(storage_paths, 100):
            q = sb.table(table).update(payload).in_("storage_path", list(chunk))
            if only_unarchived:
                q = q.is_("archived_at", "null")
            updated += len(rows(q.execute()))
    return updated


def stamp_archived(storage_paths: list[str], *, drive_id: str) -> int:
    """Mark media/story_media rows as archived into a verified Drive bundle.

    Stamps archived_at + archive_drive_id on rows whose storage_path is in the
    given set AND that are not already archived. The `archived_at IS NULL` guard
    makes re-runs idempotent: a row already stamped keeps its original timestamp,
    so the purge grace clock is never reset by a repeat archive.

    Returns the number of rows stamped this call (summed across both tables).
    """
    if not storage_paths:
        return 0
    payload = {"archived_at": datetime.now(UTC).isoformat(), "archive_drive_id": drive_id}
    stamped = _update_archived_paths(payload, storage_paths, only_unarchived=True)
    log.info("archive.stamped", count=stamped, drive_id=drive_id)
    return stamped


def list_archived_purgeable(cutoff: datetime) -> list[dict[str, Any]]:
    """Rows proven archived and past the grace window, still holding bytes.

    Gate: archived_at IS NOT NULL (proven inside a verified bundle) AND
    archived_at < cutoff (grace elapsed) AND storage_path IS NOT NULL (bytes
    still present). Only these are eligible to tombstone. Media never archived,
    or archived inside the grace window, is invisible here by construction.
    """
    sb = get_supabase()
    out: list[dict[str, Any]] = []
    for table in _ARCHIVE_TABLES:
        res = (
            sb.table(table)
            .select("id, storage_path, archive_drive_id")
            .lt("archived_at", cutoff.isoformat())
            .not_.is_("archived_at", "null")
            .not_.is_("storage_path", "null")
            .execute()
        )
        for r in rows(res):
            out.append({**r, "table": table})
    return out


def restore_media_row(
    *, post_id: str, slide_index: int, drive_id: str, storage_path: str
) -> int:
    """Un-tombstone a purged post-media row: put its storage_path back and clear
    the archive stamp. Guarded to only touch a purged row (storage_path NULL) of
    this bundle, so it can't accidentally un-archive still-present media."""
    sb = get_supabase()
    res = (
        sb.table("media")
        .update({"storage_path": storage_path, "archived_at": None,
                 "archive_drive_id": None})
        .eq("post_id", post_id)
        .eq("slide_index", slide_index)
        .eq("archive_drive_id", drive_id)
        .is_("storage_path", "null")
        .execute()
    )
    return len(rows(res))


def restore_story_media_row(
    *, story_id: str, drive_id: str, storage_path: str
) -> int:
    """Un-tombstone a purged story-media row (matched by story_id + bundle)."""
    sb = get_supabase()
    res = (
        sb.table("story_media")
        .update({"storage_path": storage_path, "archived_at": None,
                 "archive_drive_id": None})
        .eq("story_id", story_id)
        .eq("archive_drive_id", drive_id)
        .is_("storage_path", "null")
        .execute()
    )
    return len(rows(res))


def tombstone_archived(storage_paths: list[str]) -> int:
    """Null storage_path on archived rows after their bytes are removed from the
    bucket. The row stays (archived_at + archive_drive_id intact) as the ledger
    pointer to the Drive copy. Returns rows tombstoned across both tables."""
    if not storage_paths:
        return 0
    tombstoned = _update_archived_paths(
        {"storage_path": None}, storage_paths, only_unarchived=False
    )
    log.info("archive.tombstoned", count=tombstoned)
    return tombstoned


# =========================
# Run history
# =========================


def start_run(
    *,
    job_name: str,
    client_slug: str | None,
    account_handle: str | None = None,
) -> str:
    sb = get_supabase()
    res = (
        sb.table("run_history")
        .insert(
            {
                "job_name": job_name,
                "client_slug": client_slug,
                "account_handle": account_handle,
                "status": "running",
            }
        )
        .execute()
    )
    return rows(res)[0]["id"]


def finish_run(
    run_id: str,
    *,
    status: str,
    items_total: int,
    items_new: int,
    items_updated: int,
    items_failed: int,
    error_summary: str | None = None,
) -> None:
    sb = get_supabase()
    sb.table("run_history").update(
        {
            "status": status,
            "finished_at": datetime.utcnow().isoformat(),
            "items_total": items_total,
            "items_new": items_new,
            "items_updated": items_updated,
            "items_failed": items_failed,
            "error_summary": error_summary,
        }
    ).eq("id", run_id).execute()


def list_all_tracked_drive_ids() -> set[str]:
    """Every drive_file_id currently referenced by media + story_media.

    Used by the orphan sweep to decide which Live-tree Drive files are still
    tracked. Paginates in full: a truncated result would misclassify tracked
    files as orphans, so we never rely on the implicit 1000-row cap.
    """
    sb = get_supabase()
    ids: set[str] = set()
    for table in ("media", "story_media"):
        offset = 0
        page = 1000
        while True:
            res = (
                sb.table(table)
                .select("drive_file_id")
                .not_.is_("drive_file_id", "null")
                .range(offset, offset + page - 1)
                .execute()
            )
            page_rows = rows(res)
            ids.update(r["drive_file_id"] for r in page_rows)
            if len(page_rows) < page:
                break
            offset += page
    return ids


def record_item_error(
    run_id: str,
    *,
    item_ref: str | None,
    stage: str,
    error_message: str,
) -> None:
    sb = get_supabase()
    sb.table("run_item_errors").insert(
        {
            "run_id": run_id,
            "item_ref": item_ref,
            "stage": stage,
            "error_message": error_message[:2000],  # cap runaway traces
        }
    ).execute()
