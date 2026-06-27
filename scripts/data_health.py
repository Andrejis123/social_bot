"""
Data health report: `python -m scripts.data_health [--interval 7d]`.

Queries Supabase and prints a per-account markdown health table covering
scraping volume, AI classify/describe pass rates, and empty-scrape rates.

Interval tokens: yesterday | 7d (default) | 30d | 90d
"""
from __future__ import annotations

import typer

from social_bot.health import compute_health, format_report
from social_bot.logging import setup_logging

app = typer.Typer(add_completion=False)


@app.command()
def main(
    interval: str = typer.Argument("7d", help="Interval: yesterday | 7d | 30d | 90d"),
) -> None:
    setup_logging()
    rows, start, end = compute_health(interval)
    print(format_report(rows, interval, start, end))


if __name__ == "__main__":
    app()
