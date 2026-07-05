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
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

from social_bot import drive
from social_bot.db import queries
from social_bot.logging import get_logger
from social_bot.reports.data import build_period
from social_bot.storage.media import download_from_storage

log = get_logger(__name__)

DEFAULT_OUT_DIR = Path("/tmp/bundles")
# Lower concurrency to ease pressure on Supabase Storage, which drops connections
# under load. Per-download retry now lives in download_from_storage, so a
# transient blip is retried there before _safe_download ever sees a failure.
_DOWNLOAD_WORKERS = 4


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
    """Download one object, returning None if it fails after internal retries.

    download_from_storage already retries transient failures; a None here means
    it exhausted them. The caller treats any None as an incomplete bundle and
    aborts the archive (all-or-nothing), so nothing partial is ever uploaded.
    """
    try:
        data, _mime = download_from_storage(storage_path)
        return data
    except Exception as exc:
        log.warning("bundle.download_failed", path=storage_path, error=str(exc))
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

    total_bytes = 0
    written_paths: list[str] = []
    skipped = 0
    # Stream downloads through a bounded window instead of buffering the whole
    # period in one list: a large client (hundreds of story mp4s) otherwise
    # materializes every blob at once and gets OOM-killed on the ~1GB droplet.
    # We keep at most `window` downloads outstanding; each blob is written into
    # the zip and dropped before the window advances, so peak memory is
    # window x max-file, not the whole period. Writing before submitting the
    # next task holds outstanding-but-unwritten blobs at <= window. Submission
    # order (== `paths` order) is preserved, so the zip layout is deterministic.
    window = 2 * _DOWNLOAD_WORKERS
    with (
        zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf,
        ThreadPoolExecutor(max_workers=_DOWNLOAD_WORKERS) as ex,
    ):
        path_iter = iter(paths)
        inflight: deque[tuple[str, Future[bytes | None]]] = deque(
            (p, ex.submit(_safe_download, p)) for p in islice(path_iter, window)
        )
        while inflight:
            path, fut = inflight.popleft()
            blob = fut.result()
            if blob is None:
                skipped += 1
            else:
                zf.writestr(_zip_arcname(path), blob)
                written_paths.append(path)
                total_bytes += len(blob)
                del blob  # drop before advancing the window
            nxt = next(path_iter, None)
            if nxt is not None:
                inflight.append((nxt, ex.submit(_safe_download, nxt)))

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
