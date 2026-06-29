"""
Drive Live View sync pipeline.

Mirrors newly scraped media into per-client Google Drive folders so clients can
browse @account/Stories/<date>/ and @account/Posts/<date>_<id>/ without waiting
for the monthly report.

Layout under SMM - Live/<client>/:
  @<handle>/Posts/<YYYY-MM-DD>_<platform_post_id>/<slide_index>.jpg|mp4
  @<handle>/Stories/<YYYY-MM-DD>/<platform_story_id>.jpg|mp4

Only media within the rolling window_days are synced; items older than the
window are pruned from Drive and the ledger columns are cleared.

Known limitation - video playback:
  Drive's preview player transcodes videos server-side, asynchronously, and the
  queue is slow/flaky for freshly uploaded files ("It's taking longer than
  expected to process this video file for playback. Please try again later").
  This is NOT fixable in our encode: a clip that fails to preview was verified
  byte-for-byte identical in codec/profile/level/pix_fmt/faststart to one that
  plays, so the variable is Drive's processing state, not the file. Our output
  is already a standard web-playable MP4 (H.264 yuv420p + AAC + faststart).
  Genuine videos play once Drive finishes processing (minutes to hours). Static
  photo-stories, which previously looked "frozen", are now served as JPEG stills
  via is_static_video (see media_optimize), removing the most common complaint.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import get_settings
from ..db import queries
from ..drive import (
    _build_service,
    delete_file,
    list_files_recursive,
    share_folder_anyone,
    upload_bytes,
)
from ..logging import get_logger
from ..media_optimize import (
    compress_image,
    extract_poster_frame,
    is_static_video,
    transcode_video,
)
from ..storage.media import download_from_storage
from .run_context import RunContext

log = get_logger(__name__)


def _optimize(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Optimize media for the live view. Returns (bytes, mime).

    Videos are transcoded to ~480p mp4, except static photo-stories (a single
    still frame plus an audio track) which Drive renders as a frozen image with
    sound; those are served as a JPEG poster instead.
    """
    if media_type == "video":
        if is_static_video(data):
            return extract_poster_frame(data), "image/jpeg"
        return transcode_video(data), "video/mp4"
    return compress_image(data), "image/jpeg"


def _ext_from_mime(mime: str, media_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "jpg",
        "image/webp": "jpg",
        "video/mp4": "mp4",
        "video/quicktime": "mp4",
    }.get(mime, "mp4" if media_type == "video" else "jpg")


def _iso_to_eu_date(posted_at: str) -> str:
    """Convert ISO date prefix (YYYY-MM-DD) to European format (DD-MM-YYYY)."""
    raw = (posted_at or "")[:10]
    if len(raw) == 10 and raw[4] == "-":
        y, m, d = raw.split("-")
        return f"{d}-{m}-{y}"
    return raw


def _drive_folder_for_post(
    live_root: str, client_slug: str, handle: str,
    posted_at: str, platform_post_id: str,
) -> str:
    date = _iso_to_eu_date(posted_at)
    short_id = (platform_post_id or "")[-6:]
    return f"{live_root}/{client_slug}/@{handle}/Posts/{date}_{short_id}"


def _drive_folder_for_story(
    live_root: str, client_slug: str, handle: str, posted_at: str,
) -> str:
    date = _iso_to_eu_date(posted_at)
    return f"{live_root}/{client_slug}/@{handle}/Stories/{date}"


def _check_quota() -> None:
    try:
        svc = _build_service()
        about = svc.about().get(fields="storageQuota").execute()
        q = about.get("storageQuota", {})
        limit = int(q.get("limit", 0))
        used = int(q.get("usage", 0))
        if limit > 0:
            pct = used / limit * 100
            log.info("drive.quota", used_gb=round(used / 1e9, 2), limit_gb=round(limit / 1e9, 2), pct=round(pct, 1))
            if pct > 80:
                _warn_quota(pct)
    except Exception as exc:
        log.warning("drive.quota_check_failed", error=str(exc))


def _warn_quota(pct: float) -> None:
    try:
        from ..notifications.telegram import send
        send(f"Drive quota warning: {pct:.1f}% used. Live view uploads may fail soon.")
    except Exception:
        log.warning("drive.quota_warn_telegram_failed", pct=pct)


def sync_client_to_drive(client_slug: str, window_days: int = 30) -> str:
    """Mirror unsynced media to Drive and prune expired files. Returns run_id."""
    settings = get_settings()
    live_root = settings.google_drive_live_root_folder

    with RunContext(job_name="sync_drive", client_slug=client_slug, silent=True) as run:
        client_id = queries.get_client_id_by_slug(client_slug)
        if not client_id:
            log.error("sync_drive.client_not_found", slug=client_slug)
            return run.run_id

        accounts = queries.list_accounts_for_client(client_id)
        account_by_id = {a["id"]: a for a in accounts}
        account_ids = list(account_by_id.keys())

        since = datetime.now(UTC) - timedelta(days=window_days)

        # Ensure client folder exists and is shared (idempotent).
        client_folder_path = f"{live_root}/{client_slug}"
        link = share_folder_anyone(client_folder_path)
        log.info("sync_drive.live_link", client=client_slug, link=link)

        # Quota check — warn above 80%, don't block uploads.
        _check_quota()

        # --- Sync post media ---
        post_rows = queries.list_unsynced_post_media(account_ids, since)
        log.info("sync_drive.post_media.found", count=len(post_rows))

        for row in post_rows:
            run.items_total += 1
            acct = account_by_id.get(row["account_id"] or "")
            if not acct:
                run.record_item_error(row["media_id"], stage="lookup", message="account not found")
                continue
            handle = acct["handle"]
            storage_path: str = row["storage_path"]
            media_type: str = row["media_type"]

            try:
                data, mime = download_from_storage(storage_path)
            except Exception as exc:
                run.record_item_error(row["media_id"], stage="download", message=str(exc))
                continue

            try:
                data, mime = _optimize(data, media_type)
            except Exception as exc:
                log.warning("sync_drive.optimize_failed", path=storage_path, error=str(exc))
                run.record_item_error(row["media_id"], stage="optimize", message=str(exc))
                continue

            ext = _ext_from_mime(mime, media_type)
            folder_path = _drive_folder_for_post(
                live_root, client_slug, handle,
                row["posted_at"] or "", row["platform_post_id"] or "",
            )
            file_name = f"{row['slide_index']}.{ext}"

            try:
                result = upload_bytes(
                    data=data, name=file_name, drive_folder_path=folder_path,
                    mime_type=mime, overwrite=True,
                )
                queries.mark_media_synced(row["media_id"], result["id"])
                run.items_new += 1
            except Exception as exc:
                run.record_item_error(row["media_id"], stage="upload", message=str(exc))

        # --- Sync story media ---
        story_rows = queries.list_unsynced_story_media(account_ids, since)
        log.info("sync_drive.story_media.found", count=len(story_rows))

        for row in story_rows:
            run.items_total += 1
            acct = account_by_id.get(row["account_id"] or "")
            if not acct:
                run.record_item_error(row["story_media_id"], stage="lookup", message="account not found")
                continue
            handle = acct["handle"]
            storage_path = row["storage_path"]
            media_type = row["media_type"]

            try:
                data, mime = download_from_storage(storage_path)
            except Exception as exc:
                run.record_item_error(row["story_media_id"], stage="download", message=str(exc))
                continue

            try:
                data, mime = _optimize(data, media_type)
            except Exception as exc:
                log.warning("sync_drive.optimize_failed", path=storage_path, error=str(exc))
                run.record_item_error(row["story_media_id"], stage="optimize", message=str(exc))
                continue

            ext = _ext_from_mime(mime, media_type)
            folder_path = _drive_folder_for_story(
                live_root, client_slug, handle, row["posted_at"] or "",
            )
            file_name = f"{row['platform_story_id']}.{ext}"

            try:
                result = upload_bytes(
                    data=data, name=file_name, drive_folder_path=folder_path,
                    mime_type=mime, overwrite=True,
                )
                queries.mark_story_media_synced(row["story_media_id"], result["id"])
                run.items_new += 1
            except Exception as exc:
                run.record_item_error(row["story_media_id"], stage="upload", message=str(exc))

        # --- Prune expired Drive files ---
        _prune(since, run)

        return run.run_id


def sweep_drive_orphans(*, apply: bool = False) -> dict[str, Any]:
    """Delete Live-tree Drive files no longer referenced by any ledger row.

    Normal prune only removes files whose ledger row still points at them. When
    a media/story_media row is deleted outright (e.g. a Supabase data purge),
    its Drive file becomes an untracked orphan that prune can never reach. This
    sweep walks the whole Live tree and removes any file whose Drive id is in
    neither media.drive_file_id nor story_media.drive_file_id.

    Dry-run by default (apply=False): reports what would be deleted. Safety: a
    --apply run aborts if the tracked-id set is empty, which almost always means
    the ledger query failed and would otherwise classify the entire tree as
    orphaned.
    """
    settings = get_settings()
    live_root = settings.google_drive_live_root_folder

    tracked = queries.list_all_tracked_drive_ids()
    files = list_files_recursive(live_root)
    orphans = [f for f in files if f["id"] not in tracked]

    log.info(
        "drive_sweep.scan",
        total_files=len(files), tracked_ids=len(tracked), orphans=len(orphans), apply=apply,
    )
    for f in orphans:
        log.info("drive_sweep.orphan", path=f["path"], name=f["name"], will_delete=apply)

    deleted = 0
    if apply:
        if not tracked:
            raise RuntimeError(
                "refusing to delete: tracked drive-id set is empty (likely a query failure)"
            )
        for f in orphans:
            delete_file(f["id"])
            deleted += 1

    return {
        "total_files": len(files),
        "tracked_ids": len(tracked),
        "orphans": len(orphans),
        "deleted": deleted,
        "applied": apply,
        "orphan_files": orphans,
    }


def _prune(cutoff: datetime, run: RunContext) -> None:
    for row in queries.list_expired_drive_media(cutoff):
        try:
            delete_file(row["drive_file_id"])
            queries.clear_media_drive(row["media_id"])
            run.items_updated += 1
        except Exception as exc:
            log.warning("sync_drive.prune_failed", media_id=row["media_id"], error=str(exc))

    for row in queries.list_expired_drive_story_media(cutoff):
        try:
            delete_file(row["drive_file_id"])
            queries.clear_story_media_drive(row["story_media_id"])
            run.items_updated += 1
        except Exception as exc:
            log.warning("sync_drive.prune_failed", story_media_id=row["story_media_id"], error=str(exc))
