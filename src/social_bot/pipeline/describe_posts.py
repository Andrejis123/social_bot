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
from ..ai.media_sampler import fetch_storage_blobs
from ..db import queries
from ..logging import get_logger
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
    run = RunContext(job_name="describe_posts", client_slug=slug, account_handle=account_handle)
    with run:
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
    blobs = fetch_storage_blobs(media_rows, post.get("platform_post_id", ""))

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


