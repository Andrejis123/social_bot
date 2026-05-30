"""One-shot backfill: add slide_index=99 cover thumbnails for reels missing them.

Existing reels scraped before the scraper learned to store covers inline
(2026-05-29) have only the .mp4 in Supabase Storage. This script:
  1. Lists video posts with no slide_index=99 media row, scoped to one account.
  2. For each, calls HikerAPI `/v1/media/by/id` to fetch a *fresh* cover URL
     (stored URLs in raw_payload are session-bound and 403 within ~hours).
  3. Downloads the fresh JPG, uploads to Supabase Storage at the canonical
     reel-cover path, and inserts the media row.

Run: `uv run python scripts/_backfill_reel_covers.py <account_handle> [...]`
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Path setup so the script can import claude_social without -m
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from claude_social.db import queries  # noqa: E402
from claude_social.db.client import get_supabase  # noqa: E402
from claude_social.scrapers._hiker_client import HikerClient  # noqa: E402
from claude_social.scrapers.base import REEL_COVER_SLIDE_INDEX  # noqa: E402
from claude_social.storage.media import build_storage_path, download_and_upload  # noqa: E402


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def backfill_account(handle: str, client: HikerClient) -> tuple[int, int, int]:
    """Return (already_ok, backfilled, skipped) counts."""
    sb = get_supabase()
    # Find the account row
    acct_res = sb.table("accounts").select(
        "id, handle, clients(slug)"
    ).eq("handle", handle).limit(1).execute()
    if not acct_res.data:
        print(f"  ! no account row for @{handle}")
        return (0, 0, 0)
    acct = acct_res.data[0]
    client_slug = acct["clients"]["slug"]

    # Reels/videos for this account
    posts_res = (
        sb.table("posts")
        .select("id, platform_post_id, post_type, posted_at, media(slide_index, media_type)")
        .eq("account_id", acct["id"])
        .in_("post_type", ["reel", "video"])
        .execute()
    )

    already_ok = backfilled = skipped = 0
    for post in posts_res.data:
        has_cover = any(
            (m.get("slide_index") == REEL_COVER_SLIDE_INDEX
             and m.get("media_type") == "image")
            for m in (post.get("media") or [])
        )
        if has_cover:
            already_ok += 1
            continue

        pk = post["platform_post_id"]
        try:
            res = client._get("/v1/media/by/id", params={"id": pk})
        except Exception as exc:
            print(f"  ! {pk}: hiker fetch failed: {exc}")
            skipped += 1
            continue

        # Prefer image_versions2.candidates[0].url, fall back to thumbnail_url
        iv = res.get("image_versions2") or {}
        cands = iv.get("candidates") or []
        url = (cands[0].get("url") if cands and isinstance(cands[0], dict) else None) \
            or res.get("thumbnail_url")
        if not url:
            print(f"  ! {pk}: no cover URL in hiker response")
            skipped += 1
            continue

        posted_at = _parse_dt(post.get("posted_at"))
        storage_path = build_storage_path(
            client_slug=client_slug,
            account_handle=handle,
            platform="instagram",
            post_id=post["id"],
            slide_index=REEL_COVER_SLIDE_INDEX,
            media_type="image",
            source_url=url,
            posted_at=posted_at,
        )
        try:
            uploaded = download_and_upload(source_url=url, storage_path=storage_path)
        except Exception as exc:
            print(f"  ! {pk}: download failed: {exc}")
            skipped += 1
            continue

        queries.insert_media(
            post_id=post["id"],
            slide_index=REEL_COVER_SLIDE_INDEX,
            media_type="image",
            source_url=url,
            storage_path=uploaded.storage_path,
            bytes_size=uploaded.bytes_size,
        )
        backfilled += 1
        print(f"  ✓ {pk}: covered → {uploaded.storage_path}")

    return (already_ok, backfilled, skipped)


def main() -> None:
    handles = sys.argv[1:]
    if not handles:
        print("usage: _backfill_reel_covers.py <handle> [...]")
        sys.exit(1)
    api_key = os.environ.get("HIKER_API_KEY")
    if not api_key:
        print("HIKER_API_KEY not set")
        sys.exit(1)
    client = HikerClient(api_key=api_key)
    for handle in handles:
        print(f"@{handle}:")
        ok, did, skip = backfill_account(handle, client)
        print(f"  {ok} already ok, {did} backfilled, {skip} skipped")


if __name__ == "__main__":
    main()
