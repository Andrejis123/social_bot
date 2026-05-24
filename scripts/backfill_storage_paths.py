"""
One-time backfill: relocate Supabase Storage objects from the old path
scheme (no account handle) to the new one.

  Old:  {client_slug}/{platform}/{posts|stories}/{YYYY}/{MM}/.../{...}.{ext}
  New:  {client_slug}/{handle}/{platform}/{posts|stories}/{YYYY}/{MM}/.../{...}.{ext}

Default is DRY-RUN. Pass `--apply` to perform the moves.

Safety properties:
  - Idempotent: rows already in the new format are skipped.
  - Per-row try/except: a failure on one object does not abort the batch.
  - No file deletions: only `bucket.move(old, new)`, which is atomic
    in Supabase Storage — data lives at exactly one path or the other,
    never both, never neither.
  - DB update fires only on successful move.

Usage:
    # show what would move:
    uv run python -m scripts.backfill_storage_paths
    # migrate posts media only:
    uv run python -m scripts.backfill_storage_paths --apply --kind posts
    # migrate everything:
    uv run python -m scripts.backfill_storage_paths --apply --kind all
    # cap the number of moves (for incremental rollout):
    uv run python -m scripts.backfill_storage_paths --apply --limit 10
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from claude_social.config import get_settings
from claude_social.db.client import get_supabase
from claude_social.logging import get_logger

log = get_logger(__name__)


# Known platform values used as the second path component in the OLD scheme.
# If a row's second component matches one of these, it needs migration.
# If it doesn't, the row is either already migrated or in an unexpected shape.
_KNOWN_PLATFORMS = {"instagram", "facebook", "tiktok", "x"}


@dataclass(slots=True)
class MoveCandidate:
    table: str               # 'media' or 'story_media'
    row_id: str
    old_path: str
    new_path: str


def _compute_new_path(old_path: str, expected_handle: str) -> str | None:
    """Return the new path, or None if the row is already migrated / malformed.

    Old: {client}/{platform}/{posts|stories}/...
    New: {client}/{handle}/{platform}/{posts|stories}/...
    """
    if not old_path:
        return None
    parts = old_path.split("/")
    if len(parts) < 4:
        log.warning("backfill.skip.too_short", path=old_path)
        return None
    second = parts[1]
    if second == expected_handle:
        # Already migrated.
        return None
    if second not in _KNOWN_PLATFORMS:
        # Unexpected shape — neither old nor new. Skip rather than guess.
        log.warning(
            "backfill.skip.unexpected_shape",
            path=old_path,
            second=second,
            expected_handle=expected_handle,
        )
        return None
    return "/".join([parts[0], expected_handle] + parts[1:])


def _fetch_media_candidates(sb: Any) -> list[MoveCandidate]:
    """media → posts → accounts → clients embedded join."""
    rows: list[MoveCandidate] = []
    start = 0
    batch_size = 1000
    while True:
        resp = (
            sb.table("media")
            .select(
                "id, storage_path, "
                "posts!inner(accounts!inner(handle, clients!inner(slug)))"
            )
            .range(start, start + batch_size - 1)
            .execute()
        )
        page = resp.data or []
        if not page:
            break
        for r in page:
            sp = r.get("storage_path")
            handle = r.get("posts", {}).get("accounts", {}).get("handle")
            if not sp or not handle:
                continue
            new = _compute_new_path(sp, handle)
            if new is None:
                continue
            rows.append(
                MoveCandidate(
                    table="media", row_id=r["id"], old_path=sp, new_path=new
                )
            )
        if len(page) < batch_size:
            break
        start += batch_size
    return rows


def _fetch_story_media_candidates(sb: Any) -> list[MoveCandidate]:
    rows: list[MoveCandidate] = []
    start = 0
    batch_size = 1000
    while True:
        resp = (
            sb.table("story_media")
            .select(
                "id, storage_path, "
                "stories!inner(accounts!inner(handle, clients!inner(slug)))"
            )
            .range(start, start + batch_size - 1)
            .execute()
        )
        page = resp.data or []
        if not page:
            break
        for r in page:
            sp = r.get("storage_path")
            handle = r.get("stories", {}).get("accounts", {}).get("handle")
            if not sp or not handle:
                continue
            new = _compute_new_path(sp, handle)
            if new is None:
                continue
            rows.append(
                MoveCandidate(
                    table="story_media", row_id=r["id"], old_path=sp, new_path=new
                )
            )
        if len(page) < batch_size:
            break
        start += batch_size
    return rows


def _apply_move(sb: Any, bucket: str, c: MoveCandidate) -> bool:
    """Move the object and update the DB row. Returns True on success."""
    try:
        sb.storage.from_(bucket).move(c.old_path, c.new_path)
    except Exception as exc:
        log.error(
            "backfill.move.failed",
            table=c.table,
            row_id=c.row_id,
            old=c.old_path,
            new=c.new_path,
            error=str(exc),
        )
        return False
    try:
        sb.table(c.table).update({"storage_path": c.new_path}).eq("id", c.row_id).execute()
    except Exception as exc:
        # File moved but DB update failed — log loudly. Re-running will
        # detect the new path on the object (no idempotent move needed)
        # but the DB row will still point to the old path until we patch.
        log.error(
            "backfill.db_update.failed_after_move",
            table=c.table,
            row_id=c.row_id,
            new=c.new_path,
            error=str(exc),
        )
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform moves. Default is dry-run (print only).",
    )
    parser.add_argument(
        "--kind",
        choices=["posts", "stories", "all"],
        default="all",
        help="Which media to backfill. Default: all.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap on the number of moves (for incremental rollout).",
    )
    args = parser.parse_args()

    settings = get_settings()
    bucket = settings.supabase_media_bucket
    sb = get_supabase()

    print(f"# bucket: {bucket}")
    print(f"# mode:   {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"# kind:   {args.kind}")
    print(f"# limit:  {args.limit or 'none'}")
    print()

    candidates: list[MoveCandidate] = []
    if args.kind in ("posts", "all"):
        media_cands = _fetch_media_candidates(sb)
        print(f"# posts media candidates: {len(media_cands)}")
        candidates.extend(media_cands)
    if args.kind in ("stories", "all"):
        story_cands = _fetch_story_media_candidates(sb)
        print(f"# story media candidates: {len(story_cands)}")
        candidates.extend(story_cands)

    if args.limit is not None:
        candidates = candidates[: args.limit]
        print(f"# capped to limit={args.limit}")
    print(f"# total to migrate: {len(candidates)}")
    print()

    if not candidates:
        print("nothing to do.")
        return 0

    succeeded = 0
    failed = 0
    for i, c in enumerate(candidates, 1):
        if args.apply:
            ok = _apply_move(sb, bucket, c)
            mark = "OK " if ok else "ERR"
            if ok:
                succeeded += 1
            else:
                failed += 1
        else:
            mark = "DRY"
        print(f"[{i:>4}/{len(candidates)}] {mark}  {c.table}  {c.old_path}  ->  {c.new_path}")

    print()
    if args.apply:
        print(f"# done: {succeeded} succeeded, {failed} failed")
        return 0 if failed == 0 else 1
    else:
        print("# dry-run complete. Re-run with --apply to perform moves.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
