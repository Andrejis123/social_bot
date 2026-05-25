"""
Stories ingestion pipeline.

Stories are ephemeral (expire after ~24h), so we scrape them more often
than posts and store them separately.

No AI classification for stories in Phase 1 — we can add it later by reusing
`ai.classifier.classify` against a story-shaped object if a client wants it.
"""

from __future__ import annotations

from urllib.parse import urlparse

import time

from ..clients import AccountConfig, LoadedClient, load_client
from ..config import get_settings
from ..db import queries
from ..db.client import get_supabase
from ..logging import get_logger
from ..scrapers.base import ScrapedStory
from ..scrapers.registry import get_scraper
from .run_context import RunContext

log = get_logger(__name__)


def ingest_stories_for_client(
    slug: str,
    *,
    account_handle: str | None = None,
) -> list[str]:
    """If account_handle is set, only that account is processed."""
    loaded = load_client(slug)
    client_id = queries.upsert_client(loaded.slug, loaded.name)

    # Explicit --account override scrapes that handle regardless of is_active.
    if account_handle:
        accounts = [a for a in loaded.config.accounts if a.handle == account_handle]
    else:
        accounts = loaded.active_accounts

    run_ids: list[str] = []
    for account in accounts:
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
    account_row = queries.upsert_account(
        client_id=client_id,
        platform=account.platform,
        handle=account.handle,
        is_owned=account.is_owned,
    )
    account_id = account_row["id"]
    cached_pk = account_row.get("platform_account_id")
    scraper = get_scraper(account.platform)

    with RunContext(
        job_name="ingest_stories",
        client_slug=loaded.slug,
        account_handle=account.handle,
    ) as run:
        stories = scraper.scrape_stories(account.handle, platform_account_id=cached_pk)
        discovered_pk = getattr(scraper, "discovered_platform_account_id", None)
        if discovered_pk and discovered_pk != cached_pk:
            try:
                queries.set_account_platform_id(account_id, discovered_pk)
            except Exception as exc:
                log.warning("account.set_platform_id_failed", error=str(exc))
        run.items_total = len(stories)

        for story in stories:
            try:
                existing = queries.find_story(story.platform, story.platform_story_id)
                if existing:
                    # Stories don't get metrics updates — they're either new or known.
                    continue
                story_id = _insert_new_story(
                    story=story,
                    account_id=account_id,
                    client_slug=loaded.slug,
                    handle=account.handle,
                    run=run,
                )
                time.sleep(1.5)
                _maybe_classify_story(loaded, story, story_id, run)
                run.items_new += 1
            except Exception as exc:
                run.record_item_error(
                    story.platform_story_id, stage="db", message=str(exc)
                )

        return run.run_id


def _maybe_classify_story(
    loaded: LoadedClient,
    story: ScrapedStory,
    story_id: str,
    run: RunContext,
) -> None:
    from ..ai.classifier import classify_story

    try:
        result = classify_story(story=story, loaded_client=loaded)
        if result is None:
            return
        queries.update_story_ai(
            story_id,
            category=result.category,
            confidence=result.confidence,
            reasoning=result.reasoning,
            prompt_version=loaded.config.ai.prompt_version,
            provider=result.provider,
        )
        if result.provider == "openai":
            run.ai_openai_count += 1
        else:
            run.ai_gemini_count += 1
    except Exception as exc:
        queries.increment_story_ai_attempts(story_id, error=str(exc))
        run.items_ai_retry += 1
        run.record_item_error(
            story.platform_story_id, stage="ai", message=str(exc)
        )


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
                account_handle=handle,
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
    account_handle: str,
    platform: str,
    story_id: str,
    media_type: str,
    source_url: str,
) -> str:
    from datetime import datetime

    now = datetime.utcnow()
    ext = _ext_from_url(source_url, media_type)
    return (
        f"{client_slug}/{account_handle}/{platform}/stories/"
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
