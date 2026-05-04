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

from claude_social.ai.classifier import classify
from claude_social.clients import load_client
from claude_social.db import queries
from claude_social.logging import get_logger, setup_logging
from claude_social.notifications.telegram import notify_ai_exhausted, notify_ai_retry_completed
from claude_social.scrapers.base import ScrapedMedia, ScrapedPost

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
    # Track exhausted posts per client for grouped alerts
    exhausted: dict[str, list[str]] = defaultdict(list)

    for row in posts:
        post_id = row["id"]

        db_media = queries.list_media_for_post(post_id)
        media = [
            ScrapedMedia(
                slide_index=m["slide_index"],
                media_type=m["media_type"],
                source_url=m.get("source_url"),
            )
            for m in db_media
            if m.get("source_url")
        ]
        post = ScrapedPost(
            platform=row["platform"],
            platform_post_id=row["platform_post_id"],
            post_type=row["post_type"],
            caption=row.get("caption"),
            permalink=row.get("permalink"),
            posted_at=None,
            media=media,
            raw={},
        )

        account = queries.get_account_with_client(row["account_id"])
        if not account or not account.get("client_slug"):
            log.warning("retry_ai.account_not_found", post_id=post_id)
            continue

        try:
            loaded = load_client(account["client_slug"])
        except Exception as exc:
            log.warning("retry_ai.client_load_failed", post_id=post_id, error=str(exc))
            continue

        time.sleep(INTER_POST_DELAY)
        try:
            result = classify(post=post, loaded_client=loaded)
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
                exhausted[account["client_slug"]].append(post_id)
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

    # Send exhaustion alerts grouped by client
    for client_slug, post_ids in exhausted.items():
        try:
            loaded = load_client(client_slug)
            client_name = loaded.name
        except Exception:
            client_name = client_slug
        notify_ai_exhausted(
            run_id=run_id,
            client_name=client_name,
            platform="instagram",
            post_ids=post_ids,
        )


if __name__ == "__main__":
    app()
