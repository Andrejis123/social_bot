"""
CLI entrypoint: `python -m scripts.scrape_posts --client example_client --limit 5`.

Thin wrapper — real logic lives in `claude_social.pipeline.ingest_posts`.
"""

from __future__ import annotations

import typer

from claude_social.logging import get_logger, setup_logging
from claude_social.pipeline.ingest_posts import ingest_posts_for_client

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = get_logger(__name__)


@app.command()
def main(
    client: str = typer.Option(..., "--client", "-c", help="Client slug (folder name)."),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max posts per account."),
    since: str | None = typer.Option(None, "--since", help="Only fetch posts on or after this date (YYYY-MM-DD)."),
    until: str | None = typer.Option(None, "--until", help="Only fetch posts on or before this date (YYYY-MM-DD)."),
    no_ai: bool = typer.Option(
        False, "--no-ai", help="Skip AI classification (useful for debugging)."
    ),
) -> None:
    setup_logging()
    log.info("cli.scrape_posts.start", client=client, limit=limit, since=since, until=until, no_ai=no_ai)
    run_ids = ingest_posts_for_client(client, limit=limit, since=since, until=until, enable_ai=not no_ai)
    log.info("cli.scrape_posts.done", runs=run_ids)


if __name__ == "__main__":
    app()
