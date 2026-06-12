"""
Build a monthly content bundle (zip of all scraped media for a client across a
period) and upload it to Google Drive at <client_slug>/data/.

Usage:
    .venv/bin/python scripts/make_content_bundle.py <client_slug> <start> <end>

Dates are inclusive, YYYY-MM-DD, interpreted as UTC.

Zip layout mirrors Supabase storage paths so the archive is self-describing:
    <handle>/posts/<YYYY>/<MM>/<post_id>/<slide_index>.<ext>
    <handle>/stories/<YYYY>/<MM>/<story_id>/<media_index>.<ext>

Filename matches the report period style so a client opening data + report
side-by-side sees consistent naming.
"""

from __future__ import annotations

import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from claude_social import drive
from claude_social.db import queries
from claude_social.logging import get_logger
from claude_social.reports.data import build_period
from claude_social.storage.media import download_from_storage

log = get_logger(__name__)

DEFAULT_OUT_DIR = Path("/tmp/bundles")
_DOWNLOAD_WORKERS = 8


def _zip_arcname(storage_path: str) -> str:
    # Strip leading <client_slug>/ — zip is already client-scoped.
    parts = storage_path.split("/", 1)
    return parts[1] if len(parts) > 1 else storage_path


def _safe_download(storage_path: str) -> bytes | None:
    try:
        data, _mime = download_from_storage(storage_path)
        return data
    except Exception as exc:
        log.warning("bundle.download_failed", path=storage_path, error=str(exc))
        return None


def build_bundle(client_slug: str, start: datetime, end: datetime) -> Path:
    period = build_period(start, end)
    filename_label = period.label.replace(" ", "_")
    out_path = DEFAULT_OUT_DIR / f"{client_slug}_{filename_label}.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client_id = queries.get_client_id_by_slug(client_slug)
    if not client_id:
        sys.exit(f"No client found with slug={client_slug!r}")
    accounts = queries.list_accounts_for_client(client_id)
    if not accounts:
        sys.exit(f"No accounts under client {client_slug!r}")
    account_ids = [a["id"] for a in accounts]
    log.info("bundle.accounts", count=len(accounts), client=client_slug)

    posts = queries.list_posts_in_period(account_ids, start, end)
    stories = queries.list_stories_in_period(account_ids, start, end)
    log.info("bundle.discovered", posts=len(posts), stories=len(stories))

    media = queries.list_media_for_posts([p["id"] for p in posts])
    story_media = queries.list_story_media_for_stories([s["id"] for s in stories])
    log.info("bundle.media_rows", post_media=len(media), story_media=len(story_media))

    rows = media + story_media
    paths = [row["storage_path"] for row in rows]

    with ThreadPoolExecutor(max_workers=_DOWNLOAD_WORKERS) as ex:
        blobs = list(ex.map(_safe_download, paths))

    total_bytes = 0
    written = 0
    skipped = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, blob in zip(paths, blobs):
            if blob is None:
                skipped += 1
                continue
            zf.writestr(_zip_arcname(path), blob)
            written += 1
            total_bytes += len(blob)

    log.info(
        "bundle.zip_finished",
        path=str(out_path),
        files=written,
        skipped=skipped,
        bytes=total_bytes,
        size_mb=round(total_bytes / 1024 / 1024, 2),
    )
    return out_path


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit("usage: make_content_bundle.py <client_slug> <YYYY-MM-DD> <YYYY-MM-DD>")
    client_slug, start_s, end_s = sys.argv[1:]
    start = datetime.fromisoformat(start_s).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_s).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    zip_path = build_bundle(client_slug, start, end)
    result = drive.upload_bundle(client_slug, zip_path)
    print(f"Uploaded: {result['webViewLink']}")


if __name__ == "__main__":
    main()
