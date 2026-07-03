"""
Supabase Storage cost control: archive a reported period to Drive, then (a week
later) purge the bytes from the bucket — but only ever the bytes proven to live
inside a verified Drive bundle.

The free Supabase tier caps FILE STORAGE at 1 GB. Roughly one month of media
fills it, so each reported period must be archived to Drive and its bytes purged
shortly after. Run as two VPS cron jobs a week apart:

    archive <start> <end> [clients...]
        Per client, build a content-bundle zip of the period's media, upload it
        to Drive at <client>/data/, VERIFY the upload by byte size, then stamp
        the bundled rows (archived_at + archive_drive_id). Only paths that
        actually entered the verified zip are stamped — a failed download, or a
        media file in a window gap, is never stamped and so never purged.

    purge [--grace-days N] [--apply]
        Tombstone media that is (1) stamped archived, (2) past the grace window,
        and (3) still holding bytes: remove the object from the bucket and NULL
        its storage_path. The row stays as a pointer to the Drive copy. Dry-run
        by default; --apply executes and aborts if the candidate set is empty.

Dates are inclusive, YYYY-MM-DD, UTC. The archive window should match the report
window (the monthly cron uses 30-days-ago .. yesterday).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import typer

from social_bot import drive
from social_bot.db import queries
from social_bot.logging import get_logger
from social_bot.notifications import telegram
from social_bot.storage.media import delete_from_storage
from social_bot.storage.summary import render_summary, summarize_paths

from .make_content_bundle import build_bundle

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = get_logger(__name__)

DEFAULT_CLIENTS = ["agape", "ecig-monitoring", "iluminatecz"]
DEFAULT_GRACE_DAYS = 7


@app.command()
def archive(
    start: str = typer.Argument(..., help="Inclusive window start (YYYY-MM-DD)."),
    end: str = typer.Argument(..., help="Inclusive window end (YYYY-MM-DD)."),
    clients: list[str] | None = typer.Argument(
        None, help="Client slugs (default: the cron's standard set)."
    ),
) -> None:
    """Bundle a period to Drive and stamp the verified-archived rows."""
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(end).replace(
        hour=23, minute=59, second=59, tzinfo=UTC,
    )
    slugs = clients or DEFAULT_CLIENTS
    failures: list[str] = []

    for slug in slugs:
        try:
            bundle = build_bundle(slug, start_dt, end_dt)

            # All-or-nothing: a period is either fully archived or not at all.
            # Any file still missing after retries means a partial bundle, which
            # we refuse to upload or stamp. The client's media stays in Supabase
            # untouched and the period is retried next run.
            if bundle.skipped:
                raise RuntimeError(
                    f"incomplete bundle: {bundle.skipped} file(s) failed to "
                    f"download after retries; aborting archive (no partial zip, "
                    f"nothing stamped, nothing purgeable)"
                )
            if not bundle.written_paths:
                log.info("archive.empty", client=slug)
                continue

            uploaded = drive.upload_bundle(slug, bundle.zip_path)
            drive_id = uploaded["id"]

            local_size = bundle.zip_path.stat().st_size
            remote_size = drive.get_file_size(drive_id)
            if remote_size != local_size:
                # Upload truncated/corrupt — do NOT stamp; nothing becomes
                # purgeable. Next month's run rebuilds and retries.
                raise RuntimeError(
                    f"drive size mismatch local={local_size} remote={remote_size}"
                )

            stamped = queries.stamp_archived(bundle.written_paths, drive_id=drive_id)
            size_mb = round(local_size / 1024 / 1024, 2)
            summary = summarize_paths(bundle.written_paths)
            log.info(
                "archive.client_done",
                client=slug,
                drive_id=drive_id,
                link=uploaded.get("webViewLink", ""),
                written=len(bundle.written_paths),
                stamped=stamped,
                skipped=bundle.skipped,
                posts=summary.total_posts,
                stories=summary.total_stories,
                size_mb=size_mb,
            )
            telegram.notify_archive_completed(
                client_slug=slug,
                period_label=f"{start} .. {end}",
                breakdown=render_summary(summary, verb="archived"),
                size_mb=size_mb,
                drive_link=uploaded.get("webViewLink", ""),
            )
        except Exception as exc:
            log.error("archive.client_failed", client=slug, error=str(exc))
            telegram.notify_archive_failed(client_slug=slug, error=str(exc))
            failures.append(slug)

    if failures:
        raise SystemExit(f"archive failed for: {failures}")


@app.command()
def purge(
    grace_days: int = typer.Option(
        DEFAULT_GRACE_DAYS, "--grace-days",
        help="Only purge media archived at least this many days ago.",
    ),
    client: str | None = typer.Option(
        None, "--client",
        help="Restrict the purge to a single client slug (storage-path prefix).",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="Execute deletions. Without this flag the run is a dry-run preview.",
    ),
) -> None:
    """Tombstone archived, grace-expired media (storage delete + NULL path)."""
    cutoff = datetime.now(UTC) - timedelta(days=grace_days)
    candidates = queries.list_archived_purgeable(cutoff)
    if client:
        candidates = [
            c for c in candidates if c["storage_path"].startswith(f"{client}/")
        ]
    paths = [c["storage_path"] for c in candidates]

    log.info(
        "purge.candidates",
        count=len(paths),
        grace_days=grace_days,
        client=client or "all",
        cutoff=cutoff.isoformat(),
        apply=apply,
    )
    for c in candidates:
        log.info("purge.candidate", table=c["table"], path=c["storage_path"])

    if not apply:
        log.info("purge.dry_run", would_delete=len(paths))
        typer.echo(
            f"DRY RUN: {len(paths)} archived files past {grace_days}d grace would "
            f"be purged. Re-run with --apply to execute."
        )
        return

    if not paths:
        raise SystemExit("purge --apply: no purgeable candidates; aborting.")

    client_label = client or "all clients"
    try:
        removed = delete_from_storage(paths)
        tombstoned = queries.tombstone_archived(paths)
    except Exception as exc:
        log.error("purge.failed", client=client_label, error=str(exc))
        telegram.notify_purge_failed(client_label=client_label, error=str(exc))
        raise

    summary = summarize_paths(paths)
    log.info(
        "purge.done",
        removed=removed,
        tombstoned=tombstoned,
        posts=summary.total_posts,
        stories=summary.total_stories,
        items=summary.total_items,
    )
    breakdown = render_summary(summary, verb="purged")
    telegram.notify_purge_completed(client_label=client_label, breakdown=breakdown)
    typer.echo(
        f"Purged {removed} files; tombstoned {tombstoned} rows.\n{breakdown}"
    )


if __name__ == "__main__":
    app()
