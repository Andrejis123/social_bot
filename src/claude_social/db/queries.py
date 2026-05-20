"""
Typed CRUD helpers for Supabase tables.

This is the *only* module that knows about column names. Pipeline code calls
these functions — if we ever swap Supabase for raw Postgres, only this file
changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..logging import get_logger
from .client import get_supabase

log = get_logger(__name__)


# =========================
# Clients & accounts
# =========================


def upsert_client(slug: str, name: str) -> str:
    """Insert or fetch a client row. Returns client id (uuid)."""
    sb = get_supabase()
    existing = sb.table("clients").select("id").eq("slug", slug).limit(1).execute()
    if existing.data:
        return existing.data[0]["id"]
    inserted = sb.table("clients").insert({"slug": slug, "name": name}).execute()
    return inserted.data[0]["id"]


def upsert_account(
    client_id: str,
    platform: str,
    handle: str,
    is_owned: bool = True,
) -> str:
    """Insert or fetch an account row. Returns account id (uuid)."""
    sb = get_supabase()
    existing = (
        sb.table("accounts")
        .select("id")
        .eq("platform", platform)
        .eq("handle", handle)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
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
    return inserted.data[0]["id"]


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
    return res.data[0] if res.data else None


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
    return res.data[0]["id"]


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
    if not res.data:
        return None
    row = res.data
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
    client_id = client_row.data[0]["id"]

    q = sb.table("accounts").select("id").eq("client_id", client_id)
    if account_handle:
        q = q.eq("handle", account_handle)
    account_rows = q.execute()
    account_ids = [a["id"] for a in (account_rows.data or [])]
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
    return res.data or []


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
    attempts = (current.data or {}).get("ai_description_attempts", 0) + 1
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
    return res.data or []


def increment_post_ai_attempts(post_id: str, *, error: str) -> int:
    """Increment ai_attempts counter and store last error. Returns new attempt count."""
    sb = get_supabase()
    current = sb.table("posts").select("ai_attempts").eq("id", post_id).single().execute()
    attempts = (current.data or {}).get("ai_attempts", 0) + 1
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
    return res.data[0]["id"]


def list_media_for_post(post_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("media")
        .select("*")
        .eq("post_id", post_id)
        .order("slide_index")
        .execute()
    )
    return res.data or []


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
    return res.data[0] if res.data else None


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
    return res.data[0]["id"]


def list_media_for_story(story_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = (
        sb.table("story_media")
        .select("*")
        .eq("story_id", story_id)
        .execute()
    )
    return res.data or []


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
    attempts = (current.data or {}).get("ai_attempts", 0) + 1
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
    client_id = client_row.data[0]["id"]

    q = sb.table("accounts").select("id").eq("client_id", client_id)
    if account_handle:
        q = q.eq("handle", account_handle)
    account_rows = q.execute()
    account_ids = [a["id"] for a in (account_rows.data or [])]
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
    return res.data or []


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
    attempts = (current.data or {}).get("ai_description_attempts", 0) + 1
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
    return res.data[0]["id"]


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
