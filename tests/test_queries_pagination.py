"""
Pagination tests for the bulk list_* helpers in db.queries.

PostgREST silently caps a single .execute() at 1000 rows. Every bulk lister
must therefore page with .range() until a short page arrives (the pattern
already used by list_all_tracked_drive_ids). These tests back each table with
more than 1000 rows via a fake Supabase client: if the helper never calls
.range(), the fake serves exactly the first 1000 rows (simulating the cap),
so a non-paginating helper visibly truncates and the assertion fails.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from social_bot.db import queries

TOTAL = 1500  # per-table row count; anything > 1000 exposes the cap
_CAP = 1000

START = datetime(2026, 4, 1, tzinfo=UTC)
END = datetime(2026, 4, 30, tzinfo=UTC)


def _row(i: int) -> dict:
    """One universal row shaped to satisfy every list_* helper's key access."""
    return {
        "id": f"row-{i}",
        "account_id": "acct-1",
        "posted_at": "2026-04-15T00:00:00+00:00",
        "platform_post_id": f"pp-{i}",
        "platform_story_id": f"ps-{i}",
        "post_id": f"post-{i}",
        "story_id": f"story-{i}",
        "slide_index": 0,
        "media_type": "image",
        "storage_path": f"client/handle/{i}.jpg",
        "archive_drive_id": "drive-bundle-1",
        "drive_file_id": f"drive-{i}",
        "posts": {
            "id": f"post-{i}",
            "account_id": "acct-1",
            "platform_post_id": f"pp-{i}",
            "posted_at": "2026-04-15T00:00:00+00:00",
        },
        "stories": {
            "id": f"story-{i}",
            "account_id": "acct-1",
            "platform_story_id": f"ps-{i}",
            "posted_at": "2026-04-15T00:00:00+00:00",
        },
    }


class _FakeQuery:
    """Chainable query builder over a backing list.

    Filters are ignored (row content is irrelevant here); only .range()
    matters. No .range() -> serve the first 1000 rows, exactly like the
    PostgREST default cap.
    """

    def __init__(self, backing: list[dict]):
        self._backing = backing
        self._range: tuple[int, int] | None = None

    # every filter/modifier chains through unchanged
    def select(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def range(self, start: int, stop: int):
        self._range = (start, stop)
        return self

    def execute(self):
        if self._range is None:
            data = self._backing[:_CAP]
        else:
            start, stop = self._range
            data = self._backing[start : min(stop + 1, start + _CAP)]
        return SimpleNamespace(data=list(data))


class _FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self._tables[name])


def _patch_sb(monkeypatch, **tables: int):
    """Install a fake supabase whose named tables hold N rows each."""
    backing = {name: [_row(i) for i in range(n)] for name, n in tables.items()}
    monkeypatch.setattr(queries, "get_supabase", lambda: _FakeSupabase(backing))


# RED: bug 3 — passes once list_posts_in_period pages with .range()
def test_list_posts_in_period_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, posts=TOTAL)
    out = queries.list_posts_in_period(["acct-1"], START, END)
    assert len(out) == TOTAL


# RED: bug 3 — passes once list_media_for_posts pages with .range()
def test_list_media_for_posts_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, media=TOTAL)
    out = queries.list_media_for_posts(["post-1"])
    assert len(out) == TOTAL


# RED: bug 3 — passes once list_stories_in_period pages with .range()
def test_list_stories_in_period_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, stories=TOTAL)
    out = queries.list_stories_in_period(["acct-1"], START, END)
    assert len(out) == TOTAL


# RED: bug 3 — passes once list_story_media_for_stories pages with .range()
def test_list_story_media_for_stories_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, story_media=TOTAL)
    out = queries.list_story_media_for_stories(["story-1"])
    assert len(out) == TOTAL


# RED: bug 3 — passes once list_archived_purgeable pages with .range()
def test_list_archived_purgeable_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, media=TOTAL, story_media=TOTAL)
    cutoff = datetime(2026, 5, 1, tzinfo=UTC)
    out = queries.list_archived_purgeable(cutoff)
    assert len(out) == 2 * TOTAL  # both tables, in full


# RED: bug 3 — passes once list_unsynced_post_media pages with .range()
def test_list_unsynced_post_media_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, media=TOTAL)
    out = queries.list_unsynced_post_media(["acct-1"], START)
    assert len(out) == TOTAL


# RED: bug 3 — passes once list_unsynced_story_media pages with .range()
def test_list_unsynced_story_media_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, story_media=TOTAL)
    out = queries.list_unsynced_story_media(["acct-1"], START)
    assert len(out) == TOTAL


# RED: bug 3 — passes once list_expired_drive_media pages with .range()
def test_list_expired_drive_media_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, media=TOTAL)
    out = queries.list_expired_drive_media(START)
    assert len(out) == TOTAL


# RED: bug 3 — passes once list_expired_drive_story_media pages with .range()
def test_list_expired_drive_story_media_returns_all_rows(monkeypatch):
    _patch_sb(monkeypatch, story_media=TOTAL)
    out = queries.list_expired_drive_story_media(START)
    assert len(out) == TOTAL
