"""
Stories ingestion pipeline.

Stories are ephemeral (expire after ~24h), so we scrape them more often
than posts and store them separately.

No AI classification for stories in Phase 1 — we can add it later by reusing
`ai.classifier.classify` against a story-shaped object if a client wants it.
"""

from __future__ import annotations

from urllib.parse import urlparse

from ..clients import AccountConfig, LoadedClient, load_client
from ..config import get_settings
from ..db import queries
from ..db.client import get_supabase
from ..logging import get_logger
from ..scrapers.base import ScrapedStory
from ..scrapers.registry import get_scraper
from .run_context import RunContext

log = get_logger(__name__)


def ingest_stories_for_client(slug: str) -> list[str]:
    loaded = load_client(slug)
    client_id = queries.upsert_client(loaded.slug, loaded.name)

    run_ids: list[str] = []
    for account in loaded.active_accounts:
        if account.platform != "instagram":
            continue
        run_ids.append(
            _ingest_one_account(loaded=loaded, account=account, client_id=client_id)
        )
    return run_ids


def _ingest_one_account(
    *,
    loaded: LoadedClient,
    account: AccountConfig,
    client_id: str,
) -> str:
    account_id = queries.upsert_account(
        client_id=client_id,
        platform=account.platform,
        handle=account.handle,
        is_owned=account.is_owned,
    )
    scraper = get_scraper(account.platform)

    with RunContext(
        job_name="ingest_stories",
        client_slug=loaded.slug,
        account_handle=account.handle,
    ) as run:
        stories = scraper.scrape_stories(account.handle)
        run.items_total = len(stories)

        for story in stories:
            try:
                existing = queries.find_story(story.platform, story.platform_story_id)
                if existing:
                    # Stories don't get metrics updates — they're either new or known.
                    continue
                _insert_new_story(
                    story=story,
                    account_id=account_id,
                    client_slug=loaded.slug,
                    handle=account.handle,
                    run=run,
                )
                run.items_new += 1
            except Exception as exc:
                run.record_item_error(
                    story.platform_story_id, stage="db", message=str(exc)
                )

        return run.run_id


def _insert_new_story(
    *,
    story: ScrapedStory,
    account_id: str,
    client_slug: str,
    handle: str,
    run: RunContext,
) -> str:
    story_id = queries.insert_story(
        account_id=account_id,
        platform=story.platform,
        platform_story_id=story.platform_story_id,
        posted_at=story.posted_at,
        expires_at=story.expires_at,
        caption=story.caption,
        raw_payload=story.raw,
    )

    for media in story.media:
        if not media.source_url:
            run.record_item_error(
                story.platform_story_id,
                stage="download_media",
                message="no source_url on story media",
            )
            continue
        try:
            path = _build_story_storage_path(
                client_slug=client_slug,
                platform=story.platform,
                story_id=story_id,
                media_type=media.media_type,
                source_url=media.source_url,
            )
            _download_and_record(
                story_id=story_id,
                source_url=media.source_url,
                media_type=media.media_type,
                storage_path=path,
                duration=media.duration_seconds,
            )
        except Exception as exc:
            run.record_item_error(
                story.platform_story_id,
                stage="download_media",
                message=str(exc),
            )
    return story_id


# =========================
# Local helpers (small enough that a shared module is premature)
# =========================


def _build_story_storage_path(
    *,
    client_slug: str,
    platform: str,
    story_id: str,
    media_type: str,
    source_url: str,
) -> str:
    from datetime import datetime

    now = datetime.utcnow()
    ext = _ext_from_url(source_url, media_type)
    return (
        f"{client_slug}/{platform}/stories/"
        f"{now.year:04d}/{now.month:02d}/{now.day:02d}/{story_id}.{ext}"
    )


def _ext_from_url(url: str, media_type: str) -> str:
    path = urlparse(url).path
    tail = path.rsplit("/", 1)[-1]
    if "." in tail:
        ext = tail.rsplit(".", 1)[-1].lower().split("?")[0]
        if 1 <= len(ext) <= 5 and ext.isalnum():
            return ext
    return "mp4" if media_type == "video" else "jpg"


def _download_and_record(
    *,
    story_id: str,
    source_url: str,
    media_type: str,
    storage_path: str,
    duration: float | None,
) -> None:
    import httpx

    settings = get_settings()
    with httpx.Client(
        timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True
    ) as http:
        resp = http.get(source_url)
        resp.raise_for_status()
        body = resp.content
        content_type = resp.headers.get("content-type", "application/octet-stream")

    sb = get_supabase()
    sb.storage.from_(settings.supabase_media_bucket).upload(
        path=storage_path,
        file=body,
        file_options={"content-type": content_type, "upsert": "true"},
    )

    queries.insert_story_media(
        story_id=story_id,
        media_type=media_type,
        source_url=source_url,
        storage_path=storage_path,
        duration_seconds=duration,
    )
