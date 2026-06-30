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
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from social_bot import drive
from social_bot.db import queries
from social_bot.logging import get_logger
from social_bot.reports.data import build_period
from social_bot.storage.media import download_from_storage

log = get_logger(__name__)

DEFAULT_OUT_DIR = Path("/tmp/bundles")
# Lower concurrency + retries: Supabase Storage drops connections under load
# ("Server disconnected"). Fewer parallel streams and a backoff retry turn those
# transient failures into successes, so a complete bundle is the normal outcome.
_DOWNLOAD_WORKERS = 4
_DOWNLOAD_RETRIES = 4
_RETRY_BACKOFF_S = 2.0


@dataclass(slots=True)
class BundleResult:
    """Outcome of building a bundle zip.

    `written_paths` is the set of Supabase storage paths whose bytes were
    ACTUALLY written into the zip — it excludes any download that failed
    (`skipped`). The archive step stamps/purges only these paths, so a media
    file that never entered the archive is never eligible for deletion.
    """

    zip_path: Path
    written_paths: list[str]
    skipped: int
    total_bytes: int


def _zip_arcname(storage_path: str) -> str:
    # Strip leading <client_slug>/ — zip is already client-scoped.
    parts = storage_path.split("/", 1)
    return parts[1] if len(parts) > 1 else storage_path


def _safe_download(storage_path: str) -> bytes | None:
    """Download one object, retrying transient failures with linear backoff.

    Returns None only after all attempts fail. The caller treats any None as an
    incomplete bundle and aborts the archive (all-or-nothing), so retrying here
    is what keeps a throttled run from degrading into a partial archive.
    """
    last_err: Exception | None = None
    for attempt in range(1, _DOWNLOAD_RETRIES + 1):
        try:
            data, _mime = download_from_storage(storage_path)
            return data
        except Exception as exc:
            last_err = exc
            if attempt < _DOWNLOAD_RETRIES:
                time.sleep(_RETRY_BACKOFF_S * attempt)
    log.warning(
        "bundle.download_failed",
        path=storage_path,
        error=str(last_err),
        attempts=_DOWNLOAD_RETRIES,
    )
    return None


def build_bundle(client_slug: str, start: datetime, end: datetime) -> BundleResult:
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
    written_paths: list[str] = []
    skipped = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, blob in zip(paths, blobs, strict=True):
            if blob is None:
                skipped += 1
                continue
            zf.writestr(_zip_arcname(path), blob)
            written_paths.append(path)
            total_bytes += len(blob)

    log.info(
        "bundle.zip_finished",
        path=str(out_path),
        files=len(written_paths),
        skipped=skipped,
        bytes=total_bytes,
        size_mb=round(total_bytes / 1024 / 1024, 2),
    )
    return BundleResult(
        zip_path=out_path,
        written_paths=written_paths,
        skipped=skipped,
        total_bytes=total_bytes,
    )


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit("usage: make_content_bundle.py <client_slug> <YYYY-MM-DD> <YYYY-MM-DD>")
    client_slug, start_s, end_s = sys.argv[1:]
    start = datetime.fromisoformat(start_s).replace(tzinfo=UTC)
    end = datetime.fromisoformat(end_s).replace(
        hour=23, minute=59, second=59, tzinfo=UTC,
    )

    bundle = build_bundle(client_slug, start, end)
    result = drive.upload_bundle(client_slug, bundle.zip_path)
    print(f"Uploaded: {result['webViewLink']}")


if __name__ == "__main__":
    main()
