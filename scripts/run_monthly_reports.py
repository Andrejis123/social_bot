"""
Monthly report driver — called by the VPS cron.

Iterates the given client slugs, builds a Period for the supplied date window
(report-style: explicit start..end, NOT calendar month — matches the
'25 April – 25 May' convention), calls `publish_report` which renders,
uploads to Supabase, mirrors to Drive (best-effort), and notifies Telegram.

Usage:
    python -m scripts.run_monthly_reports <YYYY-MM-DD> <YYYY-MM-DD> [client ...] \
        [--platform instagram|facebook|all]

If no client slugs are passed, uses the built-in default set (the same 3 that
the posts/stories cron monitors).

--platform defaults to `instagram`: the unified per-client deck is Instagram-
only pending the cross-platform report strategy decision (separate-per-platform
vs unified). Facebook is delivered as a STANDALONE deck via `--platform facebook`.
Pass `--platform all` to render every platform's accounts into one deck once that
strategy is settled.
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from social_bot.logging import get_logger
from social_bot.reports.data import build_period
from social_bot.reports.renderer import publish_report

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = get_logger(__name__)

DEFAULT_CLIENTS = ["agape", "ecig-monitoring", "iluminatecz"]


@app.command()
def main(
    start: str = typer.Argument(..., help="Inclusive window start (YYYY-MM-DD)."),
    end: str = typer.Argument(..., help="Inclusive window end (YYYY-MM-DD)."),
    clients: list[str] | None = typer.Argument(
        None, help="Client slugs (default: the cron's standard set)."
    ),
    platform: str = typer.Option(
        "instagram", "--platform", "-p",
        help="Platform to include; 'all' renders every platform into one deck. "
             "Defaults to instagram (unified deck is IG-only for now; FB ships "
             "standalone via --platform facebook).",
    ),
    reuse_synthesis: bool = typer.Option(
        False, "--reuse-synthesis",
        help="Skip LLM passes and reuse the most recent synthesis artifact from "
             "Supabase. Use when rendering color/layout variants of an existing report.",
    ),
) -> None:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(end).replace(
        hour=23, minute=59, second=59, tzinfo=UTC,
    )
    slugs = clients or DEFAULT_CLIENTS
    period = build_period(start_dt, end_dt)

    log.info(
        "monthly_reports.start",
        clients=slugs, period=period.label, platform=platform,
    )
    failures: list[str] = []
    for slug in slugs:
        try:
            path, uploaded = publish_report(
                slug, period,
                platform=None if platform == "all" else platform,
                reuse_synthesis=reuse_synthesis,
            )
            log.info(
                "monthly_reports.client_done",
                client=slug, pptx=str(path), supabase_url=uploaded.signed_url,
            )
        except Exception as exc:
            log.error("monthly_reports.client_failed", client=slug, error=str(exc))
            failures.append(slug)

    if failures:
        raise SystemExit(f"failed clients: {failures}")
    log.info("monthly_reports.done", clients=slugs, platform=platform)


if __name__ == "__main__":
    app()
