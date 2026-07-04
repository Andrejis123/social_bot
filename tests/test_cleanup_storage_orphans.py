"""Tests for scripts.cleanup_storage_orphans, a row-INDEPENDENT sweeper for
Supabase Storage.

Row-driven cleanup (scripts/_cleanup_stale_junk.py, archive_and_purge purge)
discovers bucket objects only by walking DB rows (account -> posts ->
media.storage_path). Storage has no FK cascade from Postgres, so a row deleted
without its bytes resolved first orphans the object permanently: no row-driven
tool can rediscover it. This sweeper lists the bucket directly and deletes any
object whose path is not in the tracked set (media.storage_path UNION
story_media.storage_path).

These tests target the pure seam only, with no live Supabase / network.
"""
from __future__ import annotations

import pytest

from social_bot.storage.orphans import assert_tracked_nonempty, plan_orphans


def _obj(handle: str, post_id: str, slide: int, ext: str = "jpg") -> str:
    return f"agape/{handle}/instagram/posts/2026/06/{post_id}/{slide}.{ext}"


def test_untracked_object_is_flagged() -> None:
    # In the bucket, absent from the DB -> a ghost that must be swept.
    orphan = _obj("agapeslovensko", "ghost-1", 0)
    tracked = {_obj("agapeslovensko", "live-1", 0)}
    assert plan_orphans([orphan], tracked) == [orphan]


def test_tracked_object_is_not_flagged_and_order_is_preserved() -> None:
    # Mixed input: exactly the untracked ones come back, in original order.
    tracked_a = _obj("agapeslovensko", "live-1", 0)
    tracked_b = _obj("agapeslovensko", "live-2", 0)
    orphan_a = _obj("agapeslovensko", "ghost-1", 0)
    orphan_b = _obj("agape_bratislava", "ghost-2", 0)

    bucket = [orphan_a, tracked_a, orphan_b, tracked_b]
    tracked = {tracked_a, tracked_b}

    assert plan_orphans(bucket, tracked) == [orphan_a, orphan_b]


def test_duplicate_bucket_paths_are_deduped() -> None:
    orphan = _obj("agapeslovensko", "ghost-1", 0)
    assert plan_orphans([orphan, orphan], set()) == [orphan]


def test_empty_bucket_returns_empty() -> None:
    assert plan_orphans([], {_obj("agapeslovensko", "live-1", 0)}) == []


def test_guard_refuses_when_tracked_set_is_empty() -> None:
    # Safety guard: an empty tracked set almost always means the DB query
    # failed. Deleting then would nuke the whole bucket, so the apply path
    # must abort loudly instead.
    #
    # Interface note: the task proposed assert_tracked_nonempty raising
    # SystemExit / ValueError. The repo idiom (sweep_drive_orphans in
    # src/social_bot/pipeline/sync_drive.py) instead does an inline
    # `if not tracked: raise RuntimeError(...)`. We accept any of the three so
    # the implementation can follow the RuntimeError idiom without breaking.
    with pytest.raises((SystemExit, ValueError, RuntimeError)):
        assert_tracked_nonempty(set())


def test_guard_passes_when_tracked_set_is_nonempty() -> None:
    # A populated tracked set must not raise.
    assert_tracked_nonempty({_obj("agapeslovensko", "live-1", 0)})
