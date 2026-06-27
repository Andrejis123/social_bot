"""Save and load synthesis artifacts to/from Supabase.

One row per report run. Multiple rows for the same client+period+platform are
kept (history). --reuse-synthesis fetches the most recent row.
"""
from __future__ import annotations

from typing import cast

from ..db.client import get_supabase
from ..logging import get_logger

log = get_logger(__name__)


def save_synthesis_artifact(
    *,
    client_slug: str,
    period_label: str,
    platform: str,
    model: str,
    prompt_versions: dict[str, str],
    artifact: dict,
) -> None:
    """Insert a new synthesis artifact row. Never overwrites — history is kept."""
    get_supabase().table("synthesis_artifacts").insert({
        "client_slug": client_slug,
        "period_label": period_label,
        "platform": platform,
        "model": model,
        "prompt_versions": prompt_versions,
        "artifact": artifact,
    }).execute()
    log.info(
        "synthesis_artifact.saved",
        client=client_slug, period=period_label, platform=platform,
    )


def load_latest_synthesis_artifact(
    *,
    client_slug: str,
    period_label: str,
    platform: str,
) -> dict | None:
    """Return the most recent artifact blob for a client+period+platform, or None."""
    result = (
        get_supabase()
        .table("synthesis_artifacts")
        .select("artifact")
        .eq("client_slug", client_slug)
        .eq("period_label", period_label)
        .eq("platform", platform)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        log.info(
            "synthesis_artifact.loaded",
            client=client_slug, period=period_label, platform=platform,
        )
        return cast(dict, result.data[0]["artifact"])  # type: ignore[index,call-overload]
    return None
