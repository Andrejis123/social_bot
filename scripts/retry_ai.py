"""
CLI: `python -m scripts.retry_ai`

Finds posts with ai_category IS NULL and ai_attempts < 3, attempts classification
again using the same Gemini-first -> OpenAI-fallback logic, with a delay between
each post to avoid overloading the API.
"""

from __future__ import annotations

import time
from collections import defaultdict

import typer

from social_bot.ai.classifier import classify
from social_bot.ai.media_sampler import fetch_storage_blobs
from social_bot.clients import load_client
from social_bot.db import queries
from social_bot.logging import get_logger, setup_logging
from social_bot.notifications.telegram import notify_ai_exhausted, notify_ai_retry_completed
from social_bot.scrapers.base import ScrapedPost

app = typer.Typer(add_completion=False)
log = get_logger(__name__)

MAX_ATTEMPTS = 3
INTER_POST_DELAY = 1.5


@app.command()
def main(run_id: str = typer.Option("", "--run-id", help="Original run ID for cross-reference")) -> None:
    setup_logging()
    posts = queries.find_posts_needing_ai(max_attempts=MAX_ATTEMPTS)
    log.info("retry_ai.start", eligible=len(posts))

    if not posts:
        log.info("retry_ai.nothing_to_do")
        return

    succeeded = 0
    failed = 0
    gemini_count = 0
    openai_count = 0
    still_pending = 0
    # Track exhausted posts per (client, platform) for grouped alerts
    exhausted: dict[tuple[str, str], list[str]] = defaultdict(list)

    for row in posts:
        post_id = row["id"]

        account = queries.get_account_with_client(row["account_id"])
        if not account or not account.get("client_slug"):
            log.warning("retry_ai.account_not_found", post_id=post_id)
            continue

        try:
            loaded = load_client(account["client_slug"])
        except Exception as exc:
            log.warning("retry_ai.client_load_failed", post_id=post_id, error=str(exc))
            continue

        # Fetched last, after the skip checks above — retries fire hours after
        # the scrape, so the CDN source_url is expired and media bytes come
        # from the permanent Supabase Storage copy instead.
        blobs = fetch_storage_blobs(
            queries.list_media_for_post(post_id), row["platform_post_id"]
        )
        post = ScrapedPost(
            platform=row["platform"],
            platform_post_id=row["platform_post_id"],
            post_type=row["post_type"],
            caption=row.get("caption"),
            permalink=row.get("permalink"),
            posted_at=None,
            media=[],
            raw={},
        )

        time.sleep(INTER_POST_DELAY)
        try:
            result = classify(post=post, loaded_client=loaded, blobs=blobs)
            if result is None:
                continue
            queries.update_post_ai(
                post_id,
                category=result.category,
                confidence=result.confidence,
                reasoning=result.reasoning,
                prompt_version=loaded.config.ai.prompt_version,
                provider=result.provider,
            )
            log.info("retry_ai.classified", post_id=post_id, category=result.category, provider=result.provider)
            succeeded += 1
            if result.provider == "openai":
                openai_count += 1
            else:
                gemini_count += 1
        except Exception as exc:
            new_attempts = queries.increment_post_ai_attempts(post_id, error=str(exc))
            log.warning("retry_ai.failed", post_id=post_id, attempts=new_attempts, error=str(exc))
            failed += 1
            if new_attempts >= MAX_ATTEMPTS:
                exhausted[(account["client_slug"], row["platform"])].append(post_id)
            else:
                still_pending += 1

    # Send summary notification
    log.info("retry_ai.done", succeeded=succeeded, failed=failed)
    notify_ai_retry_completed(
        run_id=run_id,
        succeeded=succeeded,
        failed=failed,
        gemini=gemini_count,
        openai=openai_count,
        still_pending=still_pending,
    )

    # Send exhaustion alerts grouped by (client, platform)
    for (client_slug, platform), post_ids in exhausted.items():
        try:
            loaded = load_client(client_slug)
            client_name = loaded.name
        except Exception:
            client_name = client_slug
        notify_ai_exhausted(
            run_id=run_id,
            client_name=client_name,
            platform=platform,
            post_ids=post_ids,
        )


if __name__ == "__main__":
    app()
