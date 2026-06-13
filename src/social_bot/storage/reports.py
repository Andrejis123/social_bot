"""Upload generated report decks to Supabase Storage.

Path scheme:
    {client_slug}/{filename}.pptx

The bucket (default `reports`, see `SUPABASE_REPORTS_BUCKET`) is expected to
exist and be PRIVATE. Access is brokered through long-lived signed URLs so
the same link in Telegram works months later without exposing the bucket.

Idempotent: re-rendering the same period overwrites the prior upload via
`upsert=true`. Same bytes get a fresh signed URL each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from ..db.client import get_supabase
from ..logging import get_logger

log = get_logger(__name__)

# 10 years in seconds — effectively "forever" for the report use case. Supabase
# accepts arbitrarily long expiries on signed URLs; the file itself persists in
# storage regardless of URL TTL, so worst case the user re-signs from the
# dashboard.
_SIGNED_URL_TTL_SECONDS = 10 * 365 * 24 * 60 * 60

_PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


@dataclass(slots=True)
class UploadedReport:
    storage_path: str   # bucket-relative path
    signed_url: str     # long-lived URL for Telegram/manual download
    bytes_size: int


def report_storage_path(client_slug: str, pptx_path: Path) -> str:
    return f"{client_slug}/{pptx_path.name}"


def _ensure_bucket(sb, bucket: str) -> None:
    """Create the bucket on first use if it doesn't exist yet.

    Private bucket — access flows through signed URLs minted by this module.
    Listing can fail with restricted keys; in that case we attempt create and
    swallow 'already exists'-style errors.
    """
    try:
        names = {b.name for b in sb.storage.list_buckets()}
        if bucket in names:
            return
    except Exception as exc:
        log.warning("storage.list_buckets_failed", error=str(exc))
    try:
        sb.storage.create_bucket(bucket, options={"public": False})
        log.info("storage.bucket_created", bucket=bucket)
    except Exception as exc:
        # Likely a benign "already exists" race; if it's something else,
        # the upload below will surface a clearer error.
        log.warning("storage.bucket_create_skipped", bucket=bucket, error=str(exc))


def upload_report(client_slug: str, pptx_path: Path) -> UploadedReport:
    """Upload a rendered .pptx and return a signed URL.

    Bucket is auto-created on first use (private). Overwrites any prior
    upload at the same path.
    """
    settings = get_settings()
    bucket = settings.supabase_reports_bucket
    storage_path = report_storage_path(client_slug, pptx_path)

    body = pptx_path.read_bytes()
    log.info(
        "report.upload.start",
        client=client_slug, path=storage_path, bytes=len(body),
    )

    sb = get_supabase()
    _ensure_bucket(sb, bucket)
    sb.storage.from_(bucket).upload(
        path=storage_path,
        file=body,
        file_options={
            "content-type": _PPTX_MIME,
            "upsert": "true",
        },
    )

    signed = sb.storage.from_(bucket).create_signed_url(
        path=storage_path, expires_in=_SIGNED_URL_TTL_SECONDS,
    )
    # supabase-py shape: {"signedURL": "..."} on success
    signed_url = signed.get("signedURL") or signed.get("signed_url") or ""
    if not signed_url:
        raise RuntimeError(
            f"Supabase returned no signed URL for {storage_path}: {signed!r}"
        )

    log.info(
        "report.upload.done",
        client=client_slug, path=storage_path, bytes=len(body),
    )
    return UploadedReport(
        storage_path=storage_path,
        signed_url=signed_url,
        bytes_size=len(body),
    )
