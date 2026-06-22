"""
Monthly report driver — called by the VPS cron.

Iterates the given client_slugs, builds a Period for the supplied date window
(report-style: explicit start..end, NOT calendar month — matches the
'25 April – 25 May' convention), calls `publish_report` which renders,
uploads to Supabase, mirrors to Drive (best-effort), and notifies Telegram.

Usage:
    python -m scripts.run_monthly_reports <YYYY-MM-DD> <YYYY-MM-DD> [client ...]

If no client slugs are passed, uses the built-in default set (the same 3 that
the posts/stories cron monitors).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from social_bot.logging import get_logger
from social_bot.reports.data import build_period
from social_bot.reports.renderer import publish_report

log = get_logger(__name__)

DEFAULT_CLIENTS = ["agape", "ecig-monitoring", "iluminatecz"]


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(
            "usage: run_monthly_reports.py <YYYY-MM-DD> <YYYY-MM-DD> [client ...]"
        )
    start = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC)
    end = datetime.fromisoformat(sys.argv[2]).replace(
        hour=23, minute=59, second=59, tzinfo=UTC,
    )
    clients = sys.argv[3:] or DEFAULT_CLIENTS
    period = build_period(start, end)

    log.info("monthly_reports.start", clients=clients, period=period.label)
    failures: list[str] = []
    for slug in clients:
        try:
            path, uploaded = publish_report(slug, period)
            log.info(
                "monthly_reports.client_done",
                client=slug, pptx=str(path), supabase_url=uploaded.signed_url,
            )
        except Exception as exc:
            log.error("monthly_reports.client_failed", client=slug, error=str(exc))
            failures.append(slug)

    if failures:
        sys.exit(f"failed clients: {failures}")
    log.info("monthly_reports.done", clients=clients)


if __name__ == "__main__":
    main()
