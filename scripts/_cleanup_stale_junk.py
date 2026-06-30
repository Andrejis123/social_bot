"""
ONE-OFF (supervised): raw-delete stale pre-project / dropped-platform media that
predates any delivered report. Confirmed junk on 2026-06-30 — no Drive copy kept.

Targets (storage + DB rows, no archive):
    pulzecz          instagram  all      competitor backfill 2022-2023, inactive
    agape_bratislava instagram  2025     pre-project backfill (project: 2026-04-27)
    agapeslovensko   instagram  2025     pre-project backfill
    agapeslovensko   facebook   all      dropped platform (FB dropped 2026-06-27)

Each target frees the bucket (the 1 GB cap is FILE storage) and deletes the rows.
Dry-run by default; --apply executes. This is NOT the recurring archive path: it
bypasses the archive-then-tombstone invariant on purpose, for confirmed junk only.

    .venv/bin/python -m scripts._cleanup_stale_junk          # preview
    .venv/bin/python -m scripts._cleanup_stale_junk --apply  # delete
"""

from __future__ import annotations

import sys

from social_bot.db.client import get_supabase
from social_bot.logging import get_logger
from social_bot.storage.media import delete_from_storage

log = get_logger(__name__)

# (handle, platform, year|None) — year=None means the whole account.
TARGETS: list[tuple[str, str, int | None]] = [
    ("pulzecz", "instagram", None),
    ("agape_bratislava", "instagram", 2025),
    ("agapeslovensko", "instagram", 2025),
    ("agapeslovensko", "facebook", None),
]


def _account_id(handle: str, platform: str) -> str | None:
    sb = get_supabase()
    res = (
        sb.table("accounts").select("id")
        .eq("handle", handle).eq("platform", platform).limit(1).execute()
    )
    return res.data[0]["id"] if res.data else None


def _ids_in_year(rows_: list[dict], year: int | None) -> list[str]:
    if year is None:
        return [r["id"] for r in rows_]
    return [r["id"] for r in rows_ if r["posted_at"][:4] == str(year)]


def collect(handle: str, platform: str, year: int | None) -> dict:
    sb = get_supabase()
    aid = _account_id(handle, platform)
    if not aid:
        return {"label": f"{handle}/{platform}", "missing": True}

    posts = sb.table("posts").select("id, posted_at").eq("account_id", aid).execute().data or []
    post_ids = _ids_in_year(posts, year)
    stories = sb.table("stories").select("id, posted_at").eq("account_id", aid).execute().data or []
    story_ids = _ids_in_year(stories, year)

    media_paths, media_ids, sm_paths, sm_ids = [], [], [], []
    for i in range(0, len(post_ids), 200):
        for m in sb.table("media").select("id, storage_path").in_("post_id", post_ids[i:i+200]).execute().data or []:
            media_ids.append(m["id"])
            if m["storage_path"]:
                media_paths.append(m["storage_path"])
    for i in range(0, len(story_ids), 200):
        for m in sb.table("story_media").select("id, storage_path").in_("story_id", story_ids[i:i+200]).execute().data or []:
            sm_ids.append(m["id"])
            if m["storage_path"]:
                sm_paths.append(m["storage_path"])

    return {
        "label": f"{handle}/{platform}" + (f"/{year}" if year else ""),
        "missing": False,
        "post_ids": post_ids, "story_ids": story_ids,
        "media_ids": media_ids, "media_paths": media_paths,
        "sm_ids": sm_ids, "sm_paths": sm_paths,
    }


def apply_delete(plan: dict) -> None:
    sb = get_supabase()
    # Storage first (frees the cap), then child rows, then parents.
    delete_from_storage(plan["media_paths"] + plan["sm_paths"])
    for ids, table in (
        (plan["media_ids"], "media"),
        (plan["sm_ids"], "story_media"),
    ):
        for i in range(0, len(ids), 100):
            sb.table(table).delete().in_("id", ids[i:i+100]).execute()
    # post_metrics references posts; clear before deleting posts.
    for i in range(0, len(plan["post_ids"]), 100):
        chunk = plan["post_ids"][i:i+100]
        sb.table("post_metrics").delete().in_("post_id", chunk).execute()
        sb.table("posts").delete().in_("id", chunk).execute()
    for i in range(0, len(plan["story_ids"]), 100):
        sb.table("stories").delete().in_("id", plan["story_ids"][i:i+100]).execute()


def main() -> None:
    do_apply = "--apply" in sys.argv[1:]
    plans = [collect(h, p, y) for h, p, y in TARGETS]

    total_files = 0
    for plan in plans:
        if plan["missing"]:
            print(f"  {plan['label']}: NO ACCOUNT (skip)")
            continue
        nf = len(plan["media_paths"]) + len(plan["sm_paths"])
        total_files += nf
        print(
            f"  {plan['label']}: {len(plan['post_ids'])} posts, "
            f"{len(plan['story_ids'])} stories, {nf} storage files"
        )

    if not do_apply:
        print(f"\nDRY RUN: would delete {total_files} storage files. Re-run with --apply.")
        return

    if total_files == 0:
        sys.exit("--apply: nothing to delete; aborting.")
    for plan in plans:
        if not plan["missing"]:
            apply_delete(plan)
            log.info("junk.deleted", target=plan["label"])
    print(f"\nDeleted {total_files} storage files across {len(TARGETS)} targets.")


if __name__ == "__main__":
    main()
