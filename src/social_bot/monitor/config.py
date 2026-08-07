"""
Loader for `config/watering_holes.yaml`.

Kept as plain dataclasses rather than pydantic models to match the other
YAML-backed config in this repo (clients.py) and to keep the failure mode
obvious: a missing key raises at load, not mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..config import REPO_ROOT

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "watering_holes.yaml"


@dataclass(slots=True)
class KeywordSet:
    """One project's filter. `any` is the inclusion gate, `none` the veto."""

    project: str
    any: list[str]
    none: list[str] = field(default_factory=list)
    min_score: int = 65


@dataclass(slots=True)
class DraftStyle:
    max_sentences: int
    voice: str


@dataclass(slots=True)
class MonitorConfig:
    subreddits: list[str]
    max_age_hours: int
    keyword_sets: list[KeywordSet]
    draft: DraftStyle

    def keyword_set(self, project: str) -> KeywordSet:
        for ks in self.keyword_sets:
            if ks.project == project:
                return ks
        raise KeyError(
            f"No keyword_set for project {project!r} in watering_holes.yaml "
            f"(have: {[k.project for k in self.keyword_sets]})"
        )


def load_monitor_config(path: Path | None = None) -> MonitorConfig:
    """Parse the monitor YAML. Raises on a malformed or missing file."""
    target = path or DEFAULT_CONFIG_PATH
    if not target.is_file():
        raise FileNotFoundError(f"Watering-hole config not found at {target}")

    raw: dict[str, Any] = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    reddit = raw.get("reddit") or {}
    subreddits = [str(s) for s in reddit.get("subreddits") or []]
    if not subreddits:
        raise ValueError(f"{target}: reddit.subreddits is empty — nothing to poll")

    keyword_sets = [
        KeywordSet(
            project=str(entry["project"]),
            any=[str(t).lower() for t in entry.get("any") or []],
            none=[str(t).lower() for t in entry.get("none") or []],
            min_score=int(entry.get("min_score", 65)),
        )
        for entry in raw.get("keyword_sets") or []
    ]
    if not keyword_sets:
        raise ValueError(f"{target}: keyword_sets is empty — every thread would be dropped")
    for ks in keyword_sets:
        # Same reason the empty-keyword_sets guard exists: `any` is the inclusion
        # gate, so an empty list matches nothing and the run silently drops every
        # thread, which is indistinguishable from a quiet week in the logs.
        if not ks.any:
            raise ValueError(
                f"{target}: keyword_set {ks.project!r} has an empty `any` list — "
                f"every thread would be dropped"
            )

    draft_raw = raw.get("draft") or {}
    draft = DraftStyle(
        max_sentences=int(draft_raw.get("max_sentences", 4)),
        voice=str(draft_raw.get("voice", "")).strip(),
    )

    return MonitorConfig(
        subreddits=subreddits,
        max_age_hours=int(reddit.get("max_age_hours", 48)),
        keyword_sets=keyword_sets,
        draft=draft,
    )
