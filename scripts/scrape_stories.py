"""CLI: `python -m scripts.scrape_stories --client example_client`."""

from __future__ import annotations

import typer

from claude_social.logging import get_logger, setup_logging
from claude_social.pipeline.ingest_stories import ingest_stories_for_client

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = get_logger(__name__)


@app.command()
def main(
    client: str = typer.Option(..., "--client", "-c", help="Client slug (folder name)."),
) -> None:
    setup_logging()
    log.info("cli.scrape_stories.start", client=client)
    run_ids = ingest_stories_for_client(client)
    log.info("cli.scrape_stories.done", runs=run_ids)


if __name__ == "__main__":
    app()
