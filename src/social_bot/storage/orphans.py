"""Row-independent Supabase Storage orphan sweep.

Supabase Storage has no FK cascade from Postgres: deleting a media/story_media
row does not delete its bucket object. Every row-driven cleanup discovers files
by walking rows, so a row deleted without its bytes resolved first orphans the
object permanently. This sweep is the only tool that can reach those ghosts: it
lists the actual bucket and deletes any object whose path is absent from
media.storage_path UNION story_media.storage_path. It is the mandatory follow-up
to any bulk row deletion. Mirror of pipeline.sync_drive.sweep_drive_orphans.
"""

from __future__ import annotations

from ..db import queries
from ..logging import get_logger
from .media import delete_from_storage
from .usage import list_object_paths

log = get_logger(__name__)


def plan_orphans(bucket_paths: list[str], tracked_paths: set[str]) -> list[str]:
    """Return the bucket paths absent from tracked_paths, in input order, deduped."""
    seen: set[str] = set()
    orphans: list[str] = []
    for path in bucket_paths:
        if path in tracked_paths or path in seen:
            continue
        seen.add(path)
        orphans.append(path)
    return orphans


def assert_tracked_nonempty(tracked_paths: set[str]) -> None:
    """Abort before deleting if the tracked set is empty (likely a query failure)."""
    if not tracked_paths:
        raise RuntimeError(
            "refusing to delete: tracked storage-path set is empty (likely a query failure)"
        )


def sweep_storage_orphans(*, prefix: str = "", apply: bool = False) -> dict:
    """List the bucket under prefix, diff against tracked paths, delete orphans."""
    tracked = queries.list_all_tracked_storage_paths()
    bucket_paths = list_object_paths(prefix)
    orphans = plan_orphans(bucket_paths, tracked)

    log.info(
        "storage_sweep.scan",
        prefix=prefix or "<root>", total_objects=len(bucket_paths),
        tracked_paths=len(tracked), orphans=len(orphans), apply=apply,
    )
    for path in orphans:
        log.info("storage_sweep.orphan", path=path, will_delete=apply)

    deleted = 0
    if apply and orphans:
        assert_tracked_nonempty(tracked)
        deleted = delete_from_storage(orphans)

    return {
        "total_objects": len(bucket_paths),
        "tracked_paths": len(tracked),
        "orphans": len(orphans),
        "deleted": deleted,
        "applied": apply,
        "orphan_paths": orphans,
    }
