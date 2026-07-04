"""
CLI entrypoint: `python -m scripts.cleanup_storage_orphans [--prefix P] [--apply]`.

Removes Supabase Storage objects no longer referenced by any media/story_media
row (untracked orphans, left behind when a data purge or manual delete removes
rows whose bytes were never deleted). Row-INDEPENDENT: the only tool that can
reach ghosts no row-driven cleanup can, and the mandatory follow-up to any bulk
row deletion. Logic lives in `social_bot.storage.orphans` (under the type gate);
this is a thin CLI, mirroring scripts/cleanup_drive_orphans.py.

Dry-run by default: prints what would be deleted. Pass --apply to delete. An
--apply run aborts if the tracked-path set is empty (almost always a failed
query, which would otherwise classify the entire bucket as orphaned).
"""

from __future__ import annotations

import typer

from social_bot.logging import get_logger, setup_logging
from social_bot.storage.orphans import sweep_storage_orphans

app = typer.Typer(add_completion=False, no_args_is_help=False)
log = get_logger(__name__)


@app.command()
def main(
    prefix: str = typer.Option(
        "", "--prefix", help="Limit the sweep to objects under this bucket prefix (e.g. a client slug)."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Actually delete orphans (default is a dry-run report)."
    ),
) -> None:
    setup_logging()
    log.info("cli.cleanup_storage_orphans.start", prefix=prefix, apply=apply)
    result = sweep_storage_orphans(prefix=prefix, apply=apply)
    mode = "deleted" if apply else "dry-run, nothing deleted"
    typer.echo(
        f"Bucket ({prefix or 'root'}): {result['total_objects']} objects | "
        f"tracked paths: {result['tracked_paths']} | "
        f"orphans: {result['orphans']} ({mode})"
    )
    for path in result["orphan_paths"]:
        typer.echo(f"  {path}")
    if not apply and result["orphans"]:
        typer.echo("\nRe-run with --apply to delete these.")


if __name__ == "__main__":
    app()
