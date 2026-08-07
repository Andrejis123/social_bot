"""
Watering-hole monitor: `python -m scripts.watch_watering_holes [--dry-run]`.

Polls the subreddits in `config/watering_holes.yaml`, keyword-filters, scores
the survivors with Gemini, and queues anything at or above the threshold in the
Notion "Watering Hole Queue" DB for Andy to answer by hand.

Nothing here posts to Reddit. Ever. The output is a review queue.

Every stage logs its input and output counts, so an over-tight filter (queue
silently empty) is distinguishable from a quiet week (feeds genuinely dry).
"""

from __future__ import annotations

from typing import Annotated

import typer

from social_bot.logging import get_logger, setup_logging
from social_bot.monitor.config import load_monitor_config
from social_bot.monitor.filtering import dedupe_key, prefilter
from social_bot.monitor.queue import QueueClient
from social_bot.monitor.relevance import score_thread
from social_bot.monitor.sources import RedditRSSSource
from social_bot.notifications import telegram

log = get_logger(__name__)

app = typer.Typer(add_completion=False)


@app.command()
def main(
    project: str = typer.Option("Social_Bot", help="Which keyword_set in the YAML to run."),
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Score and print, write nothing to Notion.")] = False,
    limit: int = typer.Option(
        25,
        help="Cap threads sent to the LLM per run (0 = no cap). The default is a "
             "blast radius guard: a keyword edit that accidentally broadens `any` "
             "would otherwise flood the queue in a single run.",
    ),
    min_score: int = typer.Option(-1, help="Override the YAML threshold. -1 = use YAML."),
    sample_dropped: int = typer.Option(
        0, help="Print N titles the keyword filter dropped, to check it is not eating real signal."
    ),
) -> None:
    setup_logging()
    config = load_monitor_config()
    keywords = config.keyword_set(project)
    threshold = keywords.min_score if min_score < 0 else min_score

    source = RedditRSSSource()
    threads = source.fetch(config.subreddits, max_age_hours=config.max_age_hours)
    log.info("monitor.fetched", threads=len(threads), subreddits=len(config.subreddits))
    if not threads:
        log.warning("monitor.no_threads", hint="all feeds 429'd or the window is empty")
        return

    result = prefilter(threads, keywords)
    log.info(
        "monitor.prefiltered",
        examined=result.examined,
        kept=len(result.kept),
        dropped_no_match=result.dropped_no_match,
        dropped_vetoed=result.dropped_vetoed,
    )

    if sample_dropped:
        print(f"\n--- {min(sample_dropped, len(result.dropped_titles))} dropped titles ---")
        for title in result.dropped_titles[:sample_dropped]:
            print(f"  {title}")
        print()

    known: set[str] = set()
    queue: QueueClient | None = None
    if not dry_run:
        queue = QueueClient.from_settings()
        known = queue.existing_keys()

    fresh = [t for t in result.kept if dedupe_key(t) not in known]
    log.info("monitor.deduped", fresh=len(fresh), already_queued=len(result.kept) - len(fresh))

    if limit:
        fresh = fresh[:limit]

    queued = 0
    below = 0
    failed = 0
    for thread in fresh:
        try:
            verdict = score_thread(thread, draft=config.draft, min_score=threshold)
        except Exception as exc:
            # One bad thread must not sink the sweep; the next run retries it
            # (it was never queued, so it is not deduped away).
            log.warning("monitor.score_failed", url=thread.url, error=str(exc))
            failed += 1
            continue

        if verdict.score < threshold:
            below += 1
            log.info("monitor.below_threshold", url=thread.url, score=verdict.score)
            continue

        if dry_run or queue is None:
            print(f"\n[{verdict.score}] r/{thread.channel} — {thread.title}")
            print(f"  {thread.url}")
            print(f"  why: {verdict.reason}")
            print(f"  draft: {verdict.draft_reply}")
            if verdict.flags:
                print(f"  ⚠ soft pitch, rewrite before posting: {', '.join(verdict.flags)}")
        else:
            try:
                queue.push(thread, verdict, project=project)
            except Exception as exc:
                # Same reasoning as the scoring guard: a Notion 4xx/5xx on one
                # row must not discard the rest of a sweep whose feed reads and
                # Gemini calls are already paid for. Unqueued = not deduped, so
                # the next run retries the row.
                log.warning("monitor.push_failed", url=thread.url, error=str(exc))
                failed += 1
                continue
        queued += 1

    log.info(
        "monitor.done",
        queued=queued,
        below_threshold=below,
        failed=failed,
        scored=queued + below,
    )
    if (queued or failed) and not dry_run:
        # `failed` is in the trigger, not just the text: a run where every push
        # 400s would otherwise notify nothing at all and read as a quiet day.
        suffix = f", <b>{failed}</b> failed" if failed else ""
        telegram.send(
            f"🔍 Watering-hole monitor: <b>{queued}</b> new thread(s) queued "
            f"for review ({below} scored below {threshold}{suffix})."
        )


if __name__ == "__main__":
    app()
