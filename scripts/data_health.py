"""
Data health report: `python -m scripts.data_health [--interval 7d]`.

Queries Supabase and prints a per-account markdown health table covering
scraping volume, AI classify/describe pass rates, and empty-scrape rates.

Interval tokens: yesterday | 7d (default) | 30d | 90d
"""
from __future__ import annotations

import logging

import typer

from social_bot.health import compute_health, format_report
from social_bot.logging import setup_logging
from social_bot.storage.usage import compute_storage_breakdown, format_storage_breakdown

app = typer.Typer(add_completion=False)


@app.command()
def main(
    interval: str = typer.Argument("7d", help="Interval: yesterday | 7d | 30d | 90d"),
    storage: bool = typer.Option(
        True, "--storage/--no-storage",
        help="Append the bucket storage breakdown (point-in-time, vs the cap).",
    ),
) -> None:
    setup_logging()
    rows, start, end = compute_health(interval)
    print(format_report(rows, interval, start, end))
    if storage:
        # The bucket walk makes hundreds of list calls; mute per-request httpx INFO.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        print()
        print(format_storage_breakdown(compute_storage_breakdown()))


if __name__ == "__main__":
    app()
