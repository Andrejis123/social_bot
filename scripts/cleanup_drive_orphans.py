"""
CLI entrypoint: `python -m scripts.cleanup_drive_orphans [--apply]`.

Removes Drive Live-tree files that are no longer referenced by any media or
story_media ledger row (untracked orphans, e.g. left behind when a Supabase
data purge deletes rows whose Drive files were never pruned).

Dry-run by default: prints what would be deleted. Pass --apply to delete.
"""

from __future__ import annotations

import typer

from social_bot.logging import get_logger, setup_logging
from social_bot.pipeline.sync_drive import sweep_drive_orphans

app = typer.Typer(add_completion=False, no_args_is_help=False)
log = get_logger(__name__)


@app.command()
def main(
    apply: bool = typer.Option(
        False, "--apply", help="Actually delete orphans (default is a dry-run report)."
    ),
) -> None:
    setup_logging()
    log.info("cli.cleanup_drive_orphans.start", apply=apply)
    result = sweep_drive_orphans(apply=apply)
    mode = "deleted" if apply else "dry-run, nothing deleted"
    typer.echo(
        f"Live tree: {result['total_files']} files | tracked ledger ids: {result['tracked_ids']} | "
        f"orphans: {result['orphans']} ({mode})"
    )
    for f in result["orphan_files"]:
        typer.echo(f"  {f['path']}/{f['name']}")
    if not apply and result["orphans"]:
        typer.echo("\nRe-run with --apply to delete these.")


if __name__ == "__main__":
    app()
