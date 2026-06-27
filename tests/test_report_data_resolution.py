"""Account resolution + hero-heal guard for the report data layer.

Regression context: the same handle (`agapeslovensko`) lives on both
instagram and facebook for the agape client. The old loader keyed a dict by
handle alone, so the two rows collided: one platform was dropped and the
survivor was rendered twice. `load_report_data` now resolves accounts by the
`(platform, handle)` natural key, so each declared account maps to its own
`account_id` with the correct `.platform`.

All Supabase access is mocked at the `get_supabase` seam; no network or live
DB is touched. `load_client` is patched so the (platform, handle) fixture is
under test control and won't drift if a real client.yaml is edited.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from social_bot.clients import AccountConfig, ClientConfig, LoadedClient
from social_bot.reports import data as data_mod
from social_bot.reports.data import Period, _resolve_post_hero, load_report_data

# ─────────────────────────────────────────────────────────────────────
# Fake Supabase client
# ─────────────────────────────────────────────────────────────────────

class _FakeQuery:
    """Chainable query stub. Every filter/order method returns self; only
    .execute() materializes the canned rows for the table it was built for."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        res = MagicMock()
        res.data = self._rows
        return res


class _FakeSupabase:
    """Dispatches .table(name) to canned rows keyed by table name."""

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self._tables.get(name, []))


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────

CLIENT_SLUG = "agape"

# Distinct account ids per (platform, handle): distinctness is what proves the
# survivor wasn't rendered twice, so the ids must differ.
_ACCOUNT_ROWS = [
    {"id": "acc-ig-agape", "handle": "agapeslovensko", "platform": "instagram", "is_active": True},
    {"id": "acc-ig-bratislava", "handle": "agape_bratislava", "platform": "instagram", "is_active": True},
    {"id": "acc-fb-agape", "handle": "agapeslovensko", "platform": "facebook", "is_active": True},
]


def _period() -> Period:
    return Period(
        start=datetime(2026, 4, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, tzinfo=UTC),
        label="1 April - 1 May 2026",
    )


def _loaded_client() -> LoadedClient:
    """client.yaml mirror: agapeslovensko on IG and FB plus agape_bratislava.

    Order is the source of truth for rendered account order."""
    cfg = ClientConfig(
        slug=CLIENT_SLUG,
        name="Agape Slovakia",
        accounts=[
            AccountConfig(platform="instagram", handle="agapeslovensko", is_active=True),
            AccountConfig(platform="instagram", handle="agape_bratislava", is_active=True),
            AccountConfig(platform="facebook", handle="agapeslovensko", is_active=True),
        ],
    )
    return LoadedClient(config=cfg, prompt_template="", categories=[], dir=Path("/nonexistent"))


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """Patch load_client + get_supabase. Posts/stories empty so account
    resolution is exercised without dragging in media/network calls."""
    monkeypatch.setattr(data_mod, "load_client", lambda slug: _loaded_client())
    fake = _FakeSupabase(
        {
            "clients": [{"id": "client-1", "name": "Agape Slovakia", "slug": CLIENT_SLUG}],
            "accounts": _ACCOUNT_ROWS,
            "posts": [],
            "stories": [],
        }
    )
    monkeypatch.setattr(data_mod, "get_supabase", lambda: fake)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────
# 1. Natural-key resolution / no collision (core regression guard)
# ─────────────────────────────────────────────────────────────────────

def test_natural_key_resolution_no_collision(patched):
    rd = load_report_data(CLIENT_SLUG, _period(), cache_dir=patched)

    # The single line that catches the regression: the same handle on two
    # platforms resolves to two distinct accounts, in client.yaml order, each
    # with the correct platform. Under the old handle-keyed code the FB row was
    # dropped and the IG survivor rendered twice (same account_id twice).
    assert [(a.platform, a.handle) for a in rd.accounts] == [
        ("instagram", "agapeslovensko"),
        ("instagram", "agape_bratislava"),
        ("facebook", "agapeslovensko"),
    ]


def test_distinct_account_ids(patched):
    rd = load_report_data(CLIENT_SLUG, _period(), cache_dir=patched)
    ids = [a.account_id for a in rd.accounts]
    assert ids == ["acc-ig-agape", "acc-ig-bratislava", "acc-fb-agape"]
    assert len(set(ids)) == len(ids)  # no row resolved (and rendered) twice


# ─────────────────────────────────────────────────────────────────────
# 2. platform= filter
# ─────────────────────────────────────────────────────────────────────

def test_platform_filter_instagram(patched):
    rd = load_report_data(CLIENT_SLUG, _period(), cache_dir=patched, platform="instagram")
    assert [(a.platform, a.handle) for a in rd.accounts] == [
        ("instagram", "agapeslovensko"),
        ("instagram", "agape_bratislava"),
    ]


def test_platform_filter_facebook(patched):
    rd = load_report_data(CLIENT_SLUG, _period(), cache_dir=patched, platform="facebook")
    assert [(a.platform, a.handle) for a in rd.accounts] == [("facebook", "agapeslovensko")]


def test_platform_filter_none_yields_all(patched):
    rd = load_report_data(CLIENT_SLUG, _period(), cache_dir=patched, platform=None)
    assert len(rd.accounts) == 3


# ─────────────────────────────────────────────────────────────────────
# 3. AccountData.platform populated
# ─────────────────────────────────────────────────────────────────────

def test_account_data_platform_populated(patched):
    rd = load_report_data(CLIENT_SLUG, _period(), cache_dir=patched)
    fb = next(a for a in rd.accounts if a.account_id == "acc-fb-agape")
    ig = next(a for a in rd.accounts if a.account_id == "acc-ig-agape")
    assert fb.platform == "facebook"
    assert ig.platform == "instagram"


# ─────────────────────────────────────────────────────────────────────
# 4. _resolve_post_hero heal guard
# ─────────────────────────────────────────────────────────────────────

def _post_row() -> dict:
    return {
        "id": "post-1",
        "platform_post_id": "p1",
        "posted_at": "2026-04-15T12:00:00+00:00",
        "raw_payload": {"thumbnail_url": "https://example.com/cover.jpg"},
    }


def test_resolve_hero_non_instagram_skips_heal(monkeypatch, tmp_path):
    heal = MagicMock(return_value=Path("/should/not/be/used"))
    monkeypatch.setattr(data_mod, "_heal_reel_cover", heal)

    out = _resolve_post_hero(
        _post_row(), media_rows=[], cache_dir=tmp_path,
        handle="agapeslovensko", client_slug=CLIENT_SLUG, platform="facebook",
    )
    assert out is None
    heal.assert_not_called()


def test_resolve_hero_instagram_reaches_heal(monkeypatch, tmp_path):
    sentinel = tmp_path / "healed.jpg"
    heal = MagicMock(return_value=sentinel)
    monkeypatch.setattr(data_mod, "_heal_reel_cover", heal)

    out = _resolve_post_hero(
        _post_row(), media_rows=[], cache_dir=tmp_path,
        handle="agapeslovensko", client_slug=CLIENT_SLUG, platform="instagram",
    )
    assert out == sentinel
    heal.assert_called_once()
