"""
Google Drive uploader for reports and content bundles.

Folder layout under the configured root (default "SMM - Reports"):

    SMM - Reports/
      <client_slug>/
        reports/
          draft/      <- auto-uploaded .pptx lands here
          final/      <- user moves PDF here after manual export
        data/         <- monthly content bundle zips

Auth: OAuth Desktop client + long-lived refresh token (the OAuth app must be
in "In production" publishing status; otherwise refresh tokens expire after 7
days and cron silently breaks).

Folder IDs are cached locally in `.drive_folder_cache.json` (keyed by full
path string, never just leaf name) so we don't re-search Drive on every call.
"""

from __future__ import annotations

import io
import json
from functools import lru_cache
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from .config import REPO_ROOT, get_settings
from .logging import get_logger

log = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CACHE_PATH = REPO_ROOT / ".drive_folder_cache.json"
FOLDER_MIME = "application/vnd.google-apps.folder"
PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
ZIP_MIME = "application/zip"

# Subfolder names under <client_slug>/ — keep callers off raw strings.
REPORTS_DRAFT = "reports/draft"
REPORTS_FINAL = "reports/final"
DATA = "data"


def _load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            log.warning("drive.cache.corrupt_reset", path=str(CACHE_PATH))
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


@lru_cache(maxsize=1)
def _build_service():
    settings = get_settings()
    missing = [
        name
        for name, val in (
            ("GOOGLE_OAUTH_CLIENT_ID", settings.google_oauth_client_id),
            ("GOOGLE_OAUTH_CLIENT_SECRET", settings.google_oauth_client_secret),
            ("GOOGLE_OAUTH_REFRESH_TOKEN", settings.google_oauth_refresh_token),
        )
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"Drive auth not configured. Missing env: {', '.join(missing)}. "
            "Run scripts/_google_auth.py to mint a refresh token."
        )

    creds = Credentials(
        token=None,
        refresh_token=settings.google_oauth_refresh_token,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_child_folder(service, parent_id: str | None, name: str) -> str | None:
    safe_name = name.replace("'", "\\'")
    q_parts = [
        f"name = '{safe_name}'",
        f"mimeType = '{FOLDER_MIME}'",
        "trashed = false",
    ]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")
    else:
        q_parts.append("'root' in parents")
    query = " and ".join(q_parts)
    resp = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
    ).execute()
    files = resp.get("files", [])
    if not files:
        return None
    return files[0]["id"]


def _create_folder(service, parent_id: str | None, name: str) -> str:
    body: dict = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        body["parents"] = [parent_id]
    folder = service.files().create(body=body, fields="id").execute()
    return folder["id"]


def get_or_create_folder(path: str) -> str:
    """Resolve a slash-separated path under My Drive root, creating missing
    segments. Cached by full path so two clients with same leaf names don't
    collide."""
    cache = _load_cache()
    if path in cache:
        return cache[path]

    service = _build_service()
    segments = [s for s in path.split("/") if s]
    parent_id: str | None = None
    accumulated = ""
    for seg in segments:
        accumulated = f"{accumulated}/{seg}" if accumulated else seg
        if accumulated in cache:
            parent_id = cache[accumulated]
            continue
        existing = _find_child_folder(service, parent_id, seg)
        if existing:
            parent_id = existing
        else:
            parent_id = _create_folder(service, parent_id, seg)
            log.info("drive.folder.created", path=accumulated, id=parent_id)
        cache[accumulated] = parent_id

    _save_cache(cache)
    return parent_id  # type: ignore[return-value]


def _find_file_in_folder(service, parent_id: str, name: str) -> str | None:
    safe_name = name.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' and '{parent_id}' in parents and trashed = false"
    )
    resp = service.files().list(
        q=query, spaces="drive", fields="files(id, name)", pageSize=10
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def upload_file(
    *,
    local_path: Path,
    drive_folder_path: str,
    mime_type: str,
    overwrite: bool = True,
) -> dict[str, str]:
    """Upload (or replace) a single file. Returns {id, webViewLink}."""
    if not local_path.exists():
        raise FileNotFoundError(local_path)

    folder_id = get_or_create_folder(drive_folder_path)
    service = _build_service()

    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
    name = local_path.name

    existing_id = _find_file_in_folder(service, folder_id, name) if overwrite else None
    if existing_id:
        file = service.files().update(
            fileId=existing_id,
            media_body=media,
            fields="id, webViewLink",
        ).execute()
        log.info("drive.file.updated", name=name, id=file["id"])
    else:
        body = {"name": name, "parents": [folder_id]}
        file = service.files().create(
            body=body,
            media_body=media,
            fields="id, webViewLink",
        ).execute()
        log.info("drive.file.uploaded", name=name, id=file["id"])

    return {"id": file["id"], "webViewLink": file.get("webViewLink", "")}


def client_folder(client_slug: str, subfolder: str) -> str:
    settings = get_settings()
    return f"{settings.google_drive_root_folder}/{client_slug}/{subfolder}"


def upload_report(client_slug: str, pptx_path: Path) -> dict[str, str]:
    return upload_file(
        local_path=pptx_path,
        drive_folder_path=client_folder(client_slug, REPORTS_DRAFT),
        mime_type=PPTX_MIME,
    )


def upload_bundle(client_slug: str, zip_path: Path) -> dict[str, str]:
    return upload_file(
        local_path=zip_path,
        drive_folder_path=client_folder(client_slug, DATA),
        mime_type=ZIP_MIME,
    )


def upload_bytes(
    *,
    data: bytes,
    name: str,
    drive_folder_path: str,
    mime_type: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """Upload in-memory bytes to Drive. Returns {id, webViewLink}.

    overwrite=False (default) skips the find-existing call; the DB ledger already
    guards re-sync so we never duplicate.
    """
    folder_id = get_or_create_folder(drive_folder_path)
    service = _build_service()

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=True)

    existing_id = _find_file_in_folder(service, folder_id, name) if overwrite else None
    if existing_id:
        file = service.files().update(
            fileId=existing_id,
            media_body=media,
            fields="id, webViewLink",
        ).execute()
        log.info("drive.file.updated", name=name, id=file["id"])
    else:
        body = {"name": name, "parents": [folder_id]}
        file = service.files().create(
            body=body,
            media_body=media,
            fields="id, webViewLink",
        ).execute()
        log.info("drive.file.uploaded", name=name, id=file["id"])

    return {"id": file["id"], "webViewLink": file.get("webViewLink", "")}


def share_folder_anyone(folder_path: str) -> str:
    """Ensure the folder at folder_path has an anyone/reader permission.

    Idempotent — if the permission already exists, Drive returns it without
    error. Returns the folder's webViewLink.
    """
    folder_id = get_or_create_folder(folder_path)
    service = _build_service()

    try:
        service.permissions().create(
            fileId=folder_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
    except HttpError as exc:
        # drive.file scope can't propagate permissions to children created in a
        # prior session. Folder is already public; safe to ignore.
        if exc.resp.status == 403 and "appNotAuthorizedToChild" in str(exc):
            log.debug("drive.folder.share_skipped_already_public", path=folder_path)
        else:
            raise

    meta = service.files().get(fileId=folder_id, fields="webViewLink").execute()
    link: str = meta.get("webViewLink", "")
    log.info("drive.folder.shared", path=folder_path, link=link)
    return link


def list_files_recursive(folder_path: str) -> list[dict[str, str]]:
    """Walk a Drive folder tree and return every (non-folder) file.

    Each item is {id, name, path} where path is the folder path the file lives
    in. Used by the orphan sweep to enumerate the Live tree.
    """
    service = _build_service()
    root_id = get_or_create_folder(folder_path)
    files: list[dict[str, str]] = []

    def _walk(folder_id: str, path: str) -> None:
        token = None
        while True:
            resp = service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=token,
            ).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    _walk(f["id"], f"{path}/{f['name']}")
                else:
                    files.append({"id": f["id"], "name": f["name"], "path": path})
            token = resp.get("nextPageToken")
            if not token:
                break

    _walk(root_id, folder_path)
    return files


def get_file_size(file_id: str) -> int:
    """Return the byte size Drive reports for a file. Used to verify an upload
    landed intact before we trust it as the archive copy and purge the source."""
    service = _build_service()
    meta = service.files().get(fileId=file_id, fields="size").execute()
    # Google Docs/folders have no size; uploaded binaries always do.
    return int(meta.get("size", 0))


def delete_file(file_id: str) -> None:
    """Delete a Drive file by ID. Tolerates 404 (already gone)."""
    service = _build_service()
    try:
        service.files().delete(fileId=file_id).execute()
        log.info("drive.file.deleted", id=file_id)
    except HttpError as exc:
        if exc.resp.status == 404:
            log.debug("drive.file.delete_404", id=file_id)
        else:
            raise
