"""
Data health report: `python -m scripts.data_health [--interval 7d]`.

Queries Supabase and prints a per-account markdown health table covering
scraping volume, AI classify/describe pass rates, and empty-scrape rates.
`--save` additionally persists the computed rows to the health_snapshots /
storage_snapshots tables (the weekly cron uses this for trend history).

Interval tokens: yesterday | 7d (default) | 30d | 90d
"""
from __future__ import annotations

import logging

import typer

from social_bot.health import compute_health, format_report, save_health_snapshots
from social_bot.logging import setup_logging
from social_bot.storage.usage import (
    compute_storage_breakdown,
    format_storage_breakdown,
    save_storage_snapshot,
)

app = typer.Typer(add_completion=False)


@app.command()
def main(
    interval: str = typer.Argument("7d", help="Interval: yesterday | 7d | 30d | 90d"),
    storage: bool = typer.Option(
        True, "--storage/--no-storage",
        help="Append the bucket storage breakdown (point-in-time, vs the cap).",
    ),
    save: bool = typer.Option(
        False, "--save",
        help="Persist the computed rows to health_snapshots (and "
             "storage_snapshots when the storage walk runs) for trend history.",
    ),
) -> None:
    setup_logging()
    rows, start, end = compute_health(interval)
    print(format_report(rows, interval, start, end))
    breakdown = None
    if storage:
        # The bucket walk makes hundreds of list calls; mute per-request httpx INFO.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        print()
        breakdown = compute_storage_breakdown()
        print(format_storage_breakdown(breakdown))
    if save:
        saved = save_health_snapshots(rows, interval, start, end)
        if breakdown is not None:
            saved += save_storage_snapshot(breakdown)
        print(f"\nSaved {saved} snapshot row(s) to Supabase.")


if __name__ == "__main__":
    app()
