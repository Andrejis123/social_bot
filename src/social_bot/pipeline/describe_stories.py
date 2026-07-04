"""
Story description pipeline.

Same structure as describe_posts — runs after story ingestion, fetches media
from Supabase Storage, generates a thorough description per story.
"""

from __future__ import annotations

import time

from ..ai.descriptor import describe
from ..ai.media_sampler import fetch_storage_blobs
from ..db import queries
from ..logging import get_logger
from .run_context import RunContext

log = get_logger(__name__)


def describe_stories_for_client(
    slug: str,
    *,
    account_handle: str | None = None,
    sleep_between: float = 3.0,
    max_attempts: int = 3,
) -> str:
    run = RunContext(job_name="describe_stories", client_slug=slug, account_handle=account_handle)
    with run:
        stories = queries.find_stories_needing_description(slug, max_attempts=max_attempts, account_handle=account_handle)
        run.items_total = len(stories)
        log.info("describe_stories.found", count=len(stories), client=slug)

        for i, story in enumerate(stories):
            if i > 0:
                time.sleep(sleep_between)
            try:
                _describe_one(story, run)
                run.items_new += 1
            except Exception as exc:
                queries.increment_story_description_attempts(story["id"], error=str(exc))
                run.record_item_error(
                    story.get("platform_story_id"), stage="ai_description", message=str(exc)
                )


    return run.run_id


def _describe_one(story: dict, run: RunContext) -> None:
    media_rows = queries.list_media_for_story(story["id"])
    blobs = fetch_storage_blobs(media_rows, story.get("platform_story_id", ""))

    result = describe(
        caption=story.get("caption"),
        post_type="story",
        blobs=blobs,
    )
    queries.update_story_description(
        story["id"],
        description=result.description,
        provider=result.provider,
    )
    log.info(
        "describe_stories.done",
        story=story.get("platform_story_id"),
        provider=result.provider,
    )
    if result.provider == "openai":
        run.ai_openai_count += 1
    else:
        run.ai_gemini_count += 1


