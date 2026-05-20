"""
CLI entrypoint: `python -m scripts.describe_posts --client example_client`.

Generates AI descriptions for all classified-but-undescribed posts.
Typically chained after scrape_posts via `just ingest`.
"""

from __future__ import annotations

import typer

from claude_social.logging import get_logger, setup_logging
from claude_social.pipeline.describe_posts import describe_posts_for_client

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = get_logger(__name__)


@app.command()
def main(
    client: str = typer.Option(..., "--client", "-c", help="Client slug (folder name)."),
    account: str = typer.Option("", "--account", "-a", help="Instagram handle to limit to."),
    sleep: float = typer.Option(3.0, "--sleep", "-s", help="Seconds to sleep between AI calls."),
) -> None:
    setup_logging()
    handle = account or None
    log.info("cli.describe_posts.start", client=client, account=handle, sleep=sleep)
    run_id = describe_posts_for_client(client, account_handle=handle, sleep_between=sleep)
    log.info("cli.describe_posts.done", run_id=run_id)


if __name__ == "__main__":
    app()
