"""
Loader tests for config/watering_holes.yaml.

Every case writes its own temp YAML so the shipped config is free to be tuned
without breaking tests. The one exception is the guard test at the bottom,
which loads the real file to catch a broken edit to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from social_bot.monitor.config import (
    DEFAULT_CONFIG_PATH,
    MonitorConfig,
    load_monitor_config,
)

MINIMAL = """
reddit:
  subreddits:
    - marketing
    - PPC
  max_age_hours: 12
keyword_sets:
  - project: Social_Bot
    any:
      - Competitor
      - story archive
    none:
      - Hiring
    min_score: 80
draft:
  max_sentences: 3
  voice: casual commenter, no sign-off
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "watering_holes.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_parses_full_config(tmp_path: Path) -> None:
    cfg = load_monitor_config(_write(tmp_path, MINIMAL))

    assert isinstance(cfg, MonitorConfig)
    assert cfg.subreddits == ["marketing", "PPC"]
    assert cfg.max_age_hours == 12
    assert cfg.draft.max_sentences == 3
    assert cfg.draft.voice == "casual commenter, no sign-off"

    ks = cfg.keyword_set("Social_Bot")
    # Terms are lowercased at load: the filter does raw substring matching
    # against an already-lowercased haystack, so this is what makes the
    # keyword gate case-insensitive.
    assert ks.any == ["competitor", "story archive"]
    assert ks.none == ["hiring"]
    assert ks.min_score == 80


def test_defaults_applied_when_optional_keys_missing(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
reddit:
  subreddits: [marketing]
keyword_sets:
  - project: Social_Bot
    any: [competitor]
""",
    )
    cfg = load_monitor_config(path)

    assert cfg.max_age_hours == 48
    assert cfg.draft.max_sentences == 4
    assert cfg.draft.voice == ""
    ks = cfg.keyword_set("Social_Bot")
    assert ks.none == []
    assert ks.min_score == 65


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_monitor_config(tmp_path / "nope.yaml")


def test_empty_subreddits_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
reddit:
  subreddits: []
keyword_sets:
  - project: Social_Bot
    any: [competitor]
""",
    )
    with pytest.raises(ValueError, match="subreddits is empty"):
        load_monitor_config(path)


def test_empty_keyword_sets_raises(tmp_path: Path) -> None:
    # Subreddits are valid here so the failure can only be the keyword gate:
    # the subreddit check runs first in the loader.
    path = _write(
        tmp_path,
        """
reddit:
  subreddits: [marketing]
keyword_sets: []
""",
    )
    with pytest.raises(ValueError, match="keyword_sets is empty"):
        load_monitor_config(path)


def test_empty_yaml_file_raises_on_subreddits(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="subreddits is empty"):
        load_monitor_config(_write(tmp_path, ""))


def test_keyword_set_unknown_project_raises_keyerror(tmp_path: Path) -> None:
    cfg = load_monitor_config(_write(tmp_path, MINIMAL))
    with pytest.raises(KeyError, match="No keyword_set for project"):
        cfg.keyword_set("Apify_Actor")


def test_multiple_keyword_sets_select_by_project(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
reddit:
  subreddits: [marketing]
keyword_sets:
  - project: Social_Bot
    any: [competitor]
  - project: Apify_Actor
    any: [scraper]
    min_score: 40
""",
    )
    cfg = load_monitor_config(path)
    assert cfg.keyword_set("Apify_Actor").any == ["scraper"]
    assert cfg.keyword_set("Apify_Actor").min_score == 40
    assert cfg.keyword_set("Social_Bot").any == ["competitor"]


def test_shipped_config_parses() -> None:
    """Guard against a broken edit to the real config/watering_holes.yaml.

    Structure only: keyword lists and thresholds are meant to be tuned.
    """
    cfg = load_monitor_config()

    assert DEFAULT_CONFIG_PATH.is_file()
    assert cfg.subreddits, "shipped config polls no subreddits"
    assert cfg.max_age_hours > 0
    ks = cfg.keyword_set("Social_Bot")
    assert ks.any, "Social_Bot keyword set has no inclusion terms"
    assert all(term == term.lower() for term in ks.any)
    assert cfg.draft.voice, "draft voice is empty; the prompt depends on it"
