"""Failing-first tests: Reels tile must count TikTok videos as reels.

TikTok posts land with post_type='video', so the current split in
`_build_account_data` (reel vs everything else) reports total_reels=0 for
every TikTok account and shovels the videos into total_posts. Spec:

- module-level predicate `_is_reel(platform, post_type)` in
  social_bot.reports.data: True when post_type == 'reel' OR
  (platform == 'tiktok' AND post_type == 'video').
- total_reels counts posts where the predicate is True for the account's
  platform; total_posts counts the complement. TikTok 'carousel' stays in
  total_posts; Instagram behavior is unchanged.

The predicate does not exist yet, so the module-level import fails
collection with a clean ImportError until the feature lands. All Supabase
access is faked at the get_supabase seam via the shared tests.fakes fake;
no network or live DB is touched.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from social_bot.reports import data as data_mod
from social_bot.reports.data import Period, _build_account_data, _is_reel
from tests.fakes import FakeSupabase

# ─────────────────────────────────────────────────────────────────────
# 1. Predicate truth table
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("platform", "post_type", "expected"),
    [
        ("tiktok", "video", True),  # the fix: TikTok videos are reels
        ("tiktok", "carousel", False),  # stays in total_posts
        ("tiktok", "reel", True),
        ("instagram", "reel", True),  # IG unchanged
        ("instagram", "video", False),
        ("instagram", "image", False),
        ("facebook", "video", False),
    ],
)
def test_is_reel_truth_table(platform, post_type, expected):
    assert _is_reel(platform, post_type) is expected


# ─────────────────────────────────────────────────────────────────────
# 2. Totals split in _build_account_data
# ─────────────────────────────────────────────────────────────────────


def _period() -> Period:
    return Period(
        start=datetime(2026, 6, 1, tzinfo=UTC),
        end=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
        label="1 June to 30 June 2026",
    )


def _post(pid: str, post_type: str) -> dict:
    return {
        "id": pid,
        "platform_post_id": f"pp-{pid}",
        "posted_at": "2026-06-15T12:00:00+00:00",
        "post_type": post_type,
        "caption": None,
        "ai_category": None,
        "ai_description": None,
        "raw_payload": {},
    }


def _account_data(monkeypatch, tmp_path, platform: str, post_types: list[str]):
    posts = [_post(f"p{i}", t) for i, t in enumerate(post_types)]
    for p in posts:
        p["account_id"] = f"acc-{platform}"
    fake = FakeSupabase({"posts": posts, "stories": []})
    monkeypatch.setattr(data_mod, "get_supabase", lambda: fake)
    monkeypatch.setattr(data_mod, "_resolve_post_hero", lambda *a, **k: None)
    meta = {"id": f"acc-{platform}", "handle": f"{platform}_handle", "platform": platform}
    return _build_account_data(meta, _period(), tmp_path, "agape")


def test_tiktok_videos_counted_as_reels(monkeypatch, tmp_path):
    ad = _account_data(
        monkeypatch, tmp_path, "tiktok", ["video", "video", "carousel", "image"]
    )
    assert ad.total_reels == 2
    assert ad.total_posts == 2  # carousel + image stay on the posts side


def test_instagram_split_unchanged(monkeypatch, tmp_path):
    ad = _account_data(
        monkeypatch, tmp_path, "instagram", ["reel", "video", "image"]
    )
    assert ad.total_reels == 1
    assert ad.total_posts == 2
