"""
CLI entrypoint: `python -m scripts.sync_drive --client <slug> [--window-days 30]`.

Mirrors newly scraped media into the Google Drive Live View for a client and
prunes Drive files older than the window.
"""

from __future__ import annotations

import typer

from social_bot.logging import get_logger, setup_logging
from social_bot.pipeline.sync_drive import sync_client_to_drive

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = get_logger(__name__)


@app.command()
def main(
    client: str = typer.Option(..., "--client", "-c", help="Client slug (folder name)."),
    window_days: int = typer.Option(30, "--window-days", "-w", help="Rolling retention window in days."),
) -> None:
    setup_logging()
    log.info("cli.sync_drive.start", client=client, window_days=window_days)
    run_id = sync_client_to_drive(client, window_days=window_days)
    log.info("cli.sync_drive.done", run_id=run_id)


if __name__ == "__main__":
    app()
