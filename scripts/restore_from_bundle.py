"""
Restore a purged period's media from its Drive content bundle back into Supabase.

Inverse of `archive_and_purge purge`. After a purge, media bytes are gone from
the bucket and the rows are tombstoned (storage_path NULL, archive_drive_id set).
This downloads the bundle zip, re-uploads each file to its original storage path,
and restores the matching row so reports can regenerate.

The zip is self-describing: each arcname is the storage path minus the client
prefix, so `<client>/<arcname>` reconstructs the original path exactly. Rows are
matched from the path structure:
    <handle>/<platform>/posts/<Y>/<M>/<post_id>/<slide>.<ext>   -> media
    <handle>/<platform>/stories/<Y>/<M>/<D>/<story_id>.<ext>    -> story_media

Usage:
    python -m scripts.restore_from_bundle <client_slug> <drive_file_id> [--apply]

Dry-run by default: reports how many files map to rows. --apply re-uploads the
bytes and un-tombstones the rows.
"""

from __future__ import annotations

import io
import sys
import zipfile
from dataclasses import dataclass

from social_bot import drive
from social_bot.db import queries
from social_bot.logging import get_logger, setup_logging
from social_bot.storage.media import upload_to_storage

log = get_logger(__name__)


@dataclass(slots=True)
class RestorePlan:
    arcname: str  # path within the zip (== storage_path minus client prefix)
    storage_path: str
    kind: str  # "post" | "story"
    post_id: str | None = None
    slide_index: int | None = None
    story_id: str | None = None


def _parse_arcname(client_slug: str, arcname: str) -> RestorePlan | None:
    """Map a zip arcname to its storage path + the row identity to match.

    The path scheme is authored forward in storage.media.build_storage_path and
    pipeline.ingest_stories._build_story_storage_path; keep this parser in sync if
    either changes.
    """
    parts = arcname.split("/")
    if len(parts) < 4 or ".." in parts or arcname.startswith("/"):
        return None  # malformed / traversal-shaped entry; skip it
    storage_path = f"{client_slug}/{arcname}"
    kind_seg = parts[2]  # handle / platform / <posts|stories> / ...
    stem = parts[-1].rsplit(".", 1)[0]
    if kind_seg == "posts":
        return RestorePlan(
            arcname=arcname, storage_path=storage_path, kind="post",
            post_id=parts[-2], slide_index=int(stem),
        )
    if kind_seg == "stories":
        return RestorePlan(
            arcname=arcname, storage_path=storage_path, kind="story", story_id=stem,
        )
    return None


def _restore_row(plan: RestorePlan, drive_id: str) -> int:
    if plan.kind == "post":
        assert plan.post_id is not None and plan.slide_index is not None
        return queries.restore_media_row(
            post_id=plan.post_id, slide_index=plan.slide_index,
            drive_id=drive_id, storage_path=plan.storage_path,
        )
    assert plan.story_id is not None
    return queries.restore_story_media_row(
        story_id=plan.story_id, drive_id=drive_id, storage_path=plan.storage_path,
    )


def main() -> None:
    setup_logging()
    args = [a for a in sys.argv[1:] if a != "--apply"]
    do_apply = "--apply" in sys.argv[1:]
    if len(args) != 2:
        sys.exit("usage: restore_from_bundle <client_slug> <drive_file_id> [--apply]")
    client_slug, drive_id = args

    zip_bytes = drive.download_file(drive_id)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        plans: list[RestorePlan] = []
        for name in names:
            plan = _parse_arcname(client_slug, name)
            if plan is None:
                log.warning("restore.unparsed_arcname", name=name)
                continue
            plans.append(plan)

        print(f"Bundle {drive_id}: {len(names)} files, {len(plans)} parsed for restore.")
        if not do_apply:
            posts = sum(1 for p in plans if p.kind == "post")
            stories = sum(1 for p in plans if p.kind == "story")
            print(f"DRY RUN: would restore {posts} post-media + {stories} story-media. "
                  f"Re-run with --apply.")
            return

        uploaded = 0
        restored = 0
        unmatched: list[str] = []
        for plan in plans:
            upload_to_storage(plan.storage_path, zf.read(plan.arcname))
            uploaded += 1
            n = _restore_row(plan, drive_id)
            restored += n
            if n == 0:
                unmatched.append(plan.storage_path)

    log.info("restore.done", uploaded=uploaded, rows_restored=restored,
             unmatched=len(unmatched))
    print(f"Restored {uploaded} files to storage; un-tombstoned {restored} rows.")
    if unmatched:
        print(f"WARNING: {len(unmatched)} files had no matching purged row "
              f"(bytes are back, but the row was not un-tombstoned):")
        for p in unmatched[:10]:
            print(f"  {p}")


if __name__ == "__main__":
    main()
