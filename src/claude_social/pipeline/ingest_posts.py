"""
Posts ingestion pipeline.

For each active account in a client's config:
  1. Scrape posts via the platform scraper.
  2. For each post, dedupe on (platform, platform_post_id):
       - existing  → append a new metrics row (time-series).
       - new       → insert post, download + upload media, classify via AI,
                     append first metrics row.
  3. Every per-post exception is isolated so one failure never kills the run.
"""

from __future__ import annotations

from ..clients import AccountConfig, LoadedClient, load_client
from ..db import queries
from ..logging import get_logger
from ..scrapers.base import ScrapedPost
from ..scrapers.registry import get_scraper
from ..storage.media import build_storage_path, download_and_upload
from .run_context import RunContext

log = get_logger(__name__)


def ingest_posts_for_client(
    slug: str,
    *,
    limit: int | None = None,
    since: str | None = None,
    until: str | None = None,
    account_handle: str | None = None,
    enable_ai: bool = True,
) -> list[str]:
    """
    Run the posts pipeline for active accounts in the given client config.

    If account_handle is set, only that account is processed — used by cron
    entries that schedule each account individually.

    Returns the list of run_history IDs created (one per account).
    """
    loaded = load_client(slug)
    client_id = queries.upsert_client(loaded.slug, loaded.name)

    run_ids: list[str] = []
    for account in loaded.active_accounts:
        if account_handle and account.handle != account_handle:
            continue
        if account.platform != "instagram":
            # Phase 1: only Instagram. Other platforms ignored (not an error).
            log.info(
                "pipeline.account.skipped_not_instagram",
                platform=account.platform,
                handle=account.handle,
            )
            continue

        run_id = _ingest_one_account(
            loaded=loaded,
            account=account,
            client_id=client_id,
            limit=limit,
            since=since,
            until=until,
            enable_ai=enable_ai,
        )
        run_ids.append(run_id)

    return run_ids


def _ingest_one_account(
    *,
    loaded: LoadedClient,
    account: AccountConfig,
    client_id: str,
    limit: int | None,
    since: str | None,
    until: str | None,
    enable_ai: bool,
) -> str:
    account_id = queries.upsert_account(
        client_id=client_id,
        platform=account.platform,
        handle=account.handle,
        is_owned=account.is_owned,
    )
    scraper = get_scraper(account.platform)

    with RunContext(
        job_name="ingest_posts",
        client_slug=loaded.slug,
        account_handle=account.handle,
    ) as run:
        posts = scraper.scrape_posts(account.handle, limit=limit, since=since, until=until)
        run.items_total = len(posts)

        for post in posts:
            try:
                existing = queries.find_post(post.platform, post.platform_post_id)
                if existing:
                    _append_metrics(existing["id"], post)
                    run.items_updated += 1
                else:
                    post_id = _insert_new_post(
                        post=post,
                        account_id=account_id,
                        client_slug=loaded.slug,
                        handle=account.handle,
                        run=run,
                    )
                    _append_metrics(post_id, post)
                    if enable_ai:
                        import time
                        time.sleep(1.5)
                        _maybe_classify(loaded, post, post_id, run)
                    run.items_new += 1
            except Exception as exc:
                # Any unhandled failure for this post — keep going with others.
                run.record_item_error(
                    post.platform_post_id, stage="db", message=str(exc)
                )

        return run.run_id


# =========================
# Per-post steps
# =========================


def _insert_new_post(
    *,
    post: ScrapedPost,
    account_id: str,
    client_slug: str,
    handle: str,
    run: RunContext,
) -> str:
    post_id = queries.insert_post(
        account_id=account_id,
        platform=post.platform,
        platform_post_id=post.platform_post_id,
        post_type=post.post_type,
        caption=post.caption,
        permalink=post.permalink,
        posted_at=post.posted_at,
        raw_payload=post.raw,
    )

    for media in post.media:
        if not media.source_url:
            run.record_item_error(
                f"{post.platform_post_id}:{media.slide_index}",
                stage="download_media",
                message="no source_url on media",
            )
            continue
        try:
            path = build_storage_path(
                client_slug=client_slug,
                platform=post.platform,
                post_id=post_id,
                slide_index=media.slide_index,
                media_type=media.media_type,
                source_url=media.source_url,
                posted_at=post.posted_at,
            )
            uploaded = download_and_upload(
                source_url=media.source_url, storage_path=path
            )
            queries.insert_media(
                post_id=post_id,
                slide_index=media.slide_index,
                media_type=media.media_type,
                source_url=media.source_url,
                storage_path=uploaded.storage_path,
                duration_seconds=media.duration_seconds,
                width=media.width,
                height=media.height,
                bytes_size=uploaded.bytes_size,
            )
        except Exception as exc:
            # One slide failing doesn't kill the post — other slides still try,
            # post row is still valid, just missing a media row.
            run.record_item_error(
                f"{post.platform_post_id}:{media.slide_index}",
                stage="download_media",
                message=str(exc),
            )
    return post_id


def _append_metrics(post_id: str, post: ScrapedPost) -> None:
    queries.append_post_metrics(
        post_id,
        like_count=post.like_count,
        comment_count=post.comment_count,
        view_count=post.view_count,
        play_count=post.play_count,
        save_count=post.save_count,
        share_count=post.share_count,
    )


def _maybe_classify(
    loaded: LoadedClient,
    post: ScrapedPost,
    post_id: str,
    run: RunContext,
) -> None:
    """
    Run AI classification for a new post.

    Isolated in its own function so a failure here can never corrupt the
    post/media records we already wrote.
    """
    from ..ai.classifier import classify  # lazy import — AI deps are heavy

    try:
        result = classify(post=post, loaded_client=loaded)
        if result is None:
            return
        queries.update_post_ai(
            post_id,
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
        queries.increment_post_ai_attempts(post_id, error=str(exc))
        run.items_ai_retry += 1
        run.record_item_error(
            post.platform_post_id, stage="ai", message=str(exc)
        )
