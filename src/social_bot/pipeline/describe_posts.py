"""
Post description pipeline.

Runs after ingestion. For each classified post that has no description yet:
  1. Fetch media from Supabase Storage (CDN URLs expire; storage paths don't).
  2. Call the AI descriptor.
  3. Store the description.

A configurable sleep between posts keeps API rate limits comfortable.
"""

from __future__ import annotations

import time

from ..ai.descriptor import describe
from ..ai.providers.gemini import MediaBlob
from ..db import queries
from ..logging import get_logger
from ..storage.media import download_from_storage
from .run_context import RunContext

log = get_logger(__name__)


def describe_posts_for_client(
    slug: str,
    *,
    account_handle: str | None = None,
    sleep_between: float = 3.0,
    max_attempts: int = 3,
) -> str:
    """
    Generate descriptions for all classified-but-undescribed posts for this client.

    Returns the run_history ID.
    """
    with RunContext(job_name="describe_posts", client_slug=slug, account_handle=account_handle) as run:
        posts = queries.find_posts_needing_description(slug, max_attempts=max_attempts, account_handle=account_handle)
        run.items_total = len(posts)
        log.info("describe.found", count=len(posts), client=slug)

        for i, post in enumerate(posts):
            if i > 0:
                time.sleep(sleep_between)
            try:
                _describe_one(post, run)
                run.items_new += 1
            except Exception as exc:
                queries.increment_post_description_attempts(post["id"], error=str(exc))
                run.record_item_error(
                    post.get("platform_post_id"), stage="ai_description", message=str(exc)
                )

        return run.run_id


def _describe_one(post: dict, run: RunContext) -> None:
    media_rows = queries.list_media_for_post(post["id"])
    blobs = _fetch_blobs(media_rows, post.get("platform_post_id", ""))

    result = describe(
        caption=post.get("caption"),
        post_type=post["post_type"],
        blobs=blobs,
    )
    queries.update_post_description(
        post["id"],
        description=result.description,
        provider=result.provider,
    )
    log.info(
        "describe.done",
        post=post.get("platform_post_id"),
        provider=result.provider,
    )
    if result.provider == "openai":
        run.ai_openai_count += 1
    else:
        run.ai_gemini_count += 1


def _fetch_blobs(media_rows: list[dict], post_ref: str) -> list[MediaBlob]:
    sampled = _sample_media_rows(media_rows)
    blobs: list[MediaBlob] = []
    for row in sampled:
        path = row.get("storage_path")
        if not path:
            log.warning("describe.media.no_storage_path", post=post_ref, slide=row.get("slide_index"))
            continue
        try:
            data, mime = download_from_storage(path)
            blobs.append(MediaBlob(bytes_data=data, mime_type=mime))
        except Exception as exc:
            log.warning(
                "describe.media.download_failed",
                post=post_ref,
                path=path,
                error=str(exc),
            )
    return blobs


def _sample_media_rows(rows: list[dict]) -> list[dict]:
    """Mirror the classifier's pick_for_ai logic: cap carousels at first/middle/last."""
    if len(rows) <= 3:
        return rows
    return [rows[0], rows[len(rows) // 2], rows[-1]]
