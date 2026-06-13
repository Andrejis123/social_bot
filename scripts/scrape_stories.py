"""CLI: `python -m scripts.scrape_stories --client example_client`."""

from __future__ import annotations

import typer

from social_bot.logging import get_logger, setup_logging
from social_bot.pipeline.ingest_stories import ingest_stories_for_client

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = get_logger(__name__)


@app.command()
def main(
    client: str = typer.Option(..., "--client", "-c", help="Client slug (folder name)."),
    account: str | None = typer.Option(None, "--account", "-a", help="Only process this account handle (default: all accounts)."),
) -> None:
    setup_logging()
    log.info("cli.scrape_stories.start", client=client, account=account)
    run_ids = ingest_stories_for_client(client, account_handle=account)
    log.info("cli.scrape_stories.done", runs=run_ids)


if __name__ == "__main__":
    app()
