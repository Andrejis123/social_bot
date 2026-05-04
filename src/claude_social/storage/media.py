"""
Download a media URL and upload the file to Supabase Storage.

Path scheme:
    {client_slug}/{platform}/posts/{YYYY}/{MM}/{post_id}/{slide_index}.{ext}

This is human-browseable in the Supabase dashboard and makes "give me all of
Client X's March media" a single prefix query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from ..db.client import get_supabase
from ..logging import get_logger

log = get_logger(__name__)

# Reasonable defaults for social CDNs. Some media URLs are multi-megabyte videos.
_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


@dataclass(slots=True)
class UploadedMedia:
    storage_path: str
    content_type: str
    bytes_size: int


def build_storage_path(
    *,
    client_slug: str,
    platform: str,
    post_id: str,
    slide_index: int,
    media_type: str,
    source_url: str,
    posted_at: datetime | None,
) -> str:
    """Compose a deterministic object path."""
    date = posted_at or datetime.utcnow()
    ext = _guess_extension(source_url, media_type)
    return (
        f"{client_slug}/{platform}/posts/"
        f"{date.year:04d}/{date.month:02d}/{post_id}/{slide_index}.{ext}"
    )


def download_and_upload(
    *,
    source_url: str,
    storage_path: str,
) -> UploadedMedia:
    """
    Stream-download a media URL, then upload the bytes to Supabase Storage.

    Raises on any HTTP error so the caller can record it in run_item_errors.
    """
    settings = get_settings()
    bucket = settings.supabase_media_bucket

    log.debug("media.download.start", url=source_url)
    with httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as http:
        resp = http.get(source_url)
        resp.raise_for_status()
        body = resp.content
        content_type = resp.headers.get("content-type", "application/octet-stream")

    log.debug("media.upload.start", path=storage_path, bytes=len(body), ctype=content_type)
    sb = get_supabase()
    sb.storage.from_(bucket).upload(
        path=storage_path,
        file=body,
        file_options={
            "content-type": content_type,
            # Overwrite on retry instead of erroring — dedupe logic above us
            # means this only fires for new posts, but be resilient anyway.
            "upsert": "true",
        },
    )

    return UploadedMedia(
        storage_path=storage_path,
        content_type=content_type,
        bytes_size=len(body),
    )


def download_from_storage(storage_path: str) -> tuple[bytes, str]:
    """
    Download a file from Supabase Storage and return (bytes, mime_type).

    Used by the description job — original CDN URLs expire, but storage paths
    are permanent.
    """
    settings = get_settings()
    bucket = settings.supabase_media_bucket
    sb = get_supabase()
    data: bytes = sb.storage.from_(bucket).download(storage_path)
    mime = _mime_from_storage_path(storage_path)
    return data, mime


def _mime_from_storage_path(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "mp4": "video/mp4",
        "mov": "video/quicktime",
    }.get(ext, "application/octet-stream")


def _guess_extension(url: str, media_type: str) -> str:
    """Prefer URL extension; fall back to media_type."""
    path = urlparse(url).path
    if "." in path.rsplit("/", 1)[-1]:
        ext = path.rsplit(".", 1)[-1].lower()
        # Strip any stray query-like junk (rare but possible on CDNs).
        ext = ext.split("?")[0].split("#")[0]
        if 1 <= len(ext) <= 5 and ext.isalnum():
            return ext
    return "mp4" if media_type == "video" else "jpg"
