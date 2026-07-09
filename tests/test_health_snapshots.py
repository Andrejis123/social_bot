"""Failing-first tests for persisted health + storage snapshots.

Pins:

5. `social_bot.health.save_health_snapshots(rows, interval, start, end)` inserts
   one `health_snapshots` row per AccountHealth (captured_at, interval,
   period_start, period_end, account_id, handle, platform + every counter
   field on the dataclass) and returns the count.
   `social_bot.storage.usage.save_storage_snapshot(b)` inserts one
   `storage_snapshots` row per (client, kind) in `b.by_client_kind`
   (captured_at, client, kind, bytes, files) and returns the count.
6. `scripts.data_health` main gains `--save`: after printing it calls
   save_health_snapshots (always) and save_storage_snapshot (only when the
   storage walk is enabled).

Production code does not exist yet; the module-level imports of the new
symbols fail collection with a clean ImportError until it lands. The fake
Supabase is the test_archive_purge.py helper reduced to what snapshot
inserts need.
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from unittest.mock import MagicMock

from typer.testing import CliRunner

import scripts.data_health as dh
import social_bot.health as health_mod
import social_bot.storage.usage as usage_mod
from social_bot.health import AccountHealth, save_health_snapshots
from social_bot.storage.usage import StorageBreakdown, save_storage_snapshot
from tests.fakes import FakeSupabase as _FakeSB

# ─────────────────────────────────────────────────────────────────────
# 5a. save_health_snapshots
# ─────────────────────────────────────────────────────────────────────

_IDENTITY_FIELDS = {"handle", "account_id", "platform"}
# Every non-identity field on AccountHealth is a counter that must persist.
_COUNTER_FIELDS = [
    f.name for f in dataclasses.fields(AccountHealth)
    if f.name not in _IDENTITY_FIELDS
]

_START = datetime(2026, 6, 1, tzinfo=UTC)
_END = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)


def _acct(handle: str, base: int) -> AccountHealth:
    """AccountHealth with a distinct value per counter (base, base+1, ...)."""
    row = AccountHealth(
        handle=handle, account_id=f"acc-{handle}", platform="instagram"
    )
    for offset, name in enumerate(_COUNTER_FIELDS):
        setattr(row, name, base + offset)
    return row


def test_save_health_snapshots_persists_every_counter(monkeypatch):
    sb = _FakeSB({"health_snapshots": []})
    monkeypatch.setattr(health_mod, "get_supabase", lambda: sb)
    rows_in = [_acct("agape", 100), _acct("ecig", 200)]

    n = save_health_snapshots(rows_in, "30d", _START, _END)

    assert n == 2
    saved = sb.tables["health_snapshots"]
    assert len(saved) == 2
    by_handle = {r["handle"]: r for r in saved}
    for src in rows_in:
        row = by_handle[src.handle]
        assert row["account_id"] == src.account_id
        assert row["platform"] == "instagram"
        assert row["interval"] == "30d"
        assert row["captured_at"]
        assert str(row["period_start"]).startswith("2026-06-01")
        assert str(row["period_end"]).startswith("2026-06-30")
        for name in _COUNTER_FIELDS:
            assert row[name] == getattr(src, name), name


def test_save_health_snapshots_empty_returns_zero(monkeypatch):
    sb = _FakeSB({"health_snapshots": []})
    monkeypatch.setattr(health_mod, "get_supabase", lambda: sb)

    assert save_health_snapshots([], "7d", _START, _END) == 0
    assert sb.tables["health_snapshots"] == []


# ─────────────────────────────────────────────────────────────────────
# 5b. save_storage_snapshot
# ─────────────────────────────────────────────────────────────────────


def test_save_storage_snapshot_one_row_per_client_kind(monkeypatch):
    sb = _FakeSB({"storage_snapshots": []})
    monkeypatch.setattr(usage_mod, "get_supabase", lambda: sb)
    b = StorageBreakdown(
        total_bytes=180,
        total_files=6,
        by_client_kind={
            ("agape", "posts"): [100, 2],
            ("agape", "stories"): [50, 1],
            ("ecig", "posts"): [30, 3],
        },
    )

    n = save_storage_snapshot(b)

    assert n == 3
    saved = sb.tables["storage_snapshots"]
    assert len(saved) == 3
    assert all(r["captured_at"] for r in saved)
    shaped = {(r["client"], r["kind"]): (r["bytes"], r["files"]) for r in saved}
    assert shaped == {
        ("agape", "posts"): (100, 2),
        ("agape", "stories"): (50, 1),
        ("ecig", "posts"): (30, 3),
    }


def test_save_storage_snapshot_empty_returns_zero(monkeypatch):
    sb = _FakeSB({"storage_snapshots": []})
    monkeypatch.setattr(usage_mod, "get_supabase", lambda: sb)

    assert save_storage_snapshot(StorageBreakdown()) == 0
    assert sb.tables["storage_snapshots"] == []


# ─────────────────────────────────────────────────────────────────────
# 6. data_health --save wiring
# ─────────────────────────────────────────────────────────────────────

_runner = CliRunner()


def _patch_data_health(monkeypatch):
    rows_sentinel = [object()]
    breakdown_sentinel = object()
    monkeypatch.setattr(
        dh, "compute_health", lambda interval: (rows_sentinel, _START, _END)
    )
    monkeypatch.setattr(dh, "format_report", lambda *a, **k: "REPORT")
    monkeypatch.setattr(dh, "compute_storage_breakdown", lambda: breakdown_sentinel)
    monkeypatch.setattr(dh, "format_storage_breakdown", lambda b, **k: "STORAGE")
    save_health = MagicMock(return_value=1)
    save_storage = MagicMock(return_value=1)
    monkeypatch.setattr(dh, "save_health_snapshots", save_health, raising=False)
    monkeypatch.setattr(dh, "save_storage_snapshot", save_storage, raising=False)
    return rows_sentinel, breakdown_sentinel, save_health, save_storage


def test_data_health_save_persists_both(monkeypatch):
    rows_sentinel, breakdown_sentinel, save_health, save_storage = (
        _patch_data_health(monkeypatch)
    )

    result = _runner.invoke(dh.app, ["7d", "--save"])

    assert result.exit_code == 0, result.output
    save_health.assert_called_once_with(rows_sentinel, "7d", _START, _END)
    save_storage.assert_called_once_with(breakdown_sentinel)


def test_data_health_save_no_storage_skips_storage_snapshot(monkeypatch):
    rows_sentinel, _breakdown, save_health, save_storage = (
        _patch_data_health(monkeypatch)
    )

    result = _runner.invoke(dh.app, ["30d", "--save", "--no-storage"])

    assert result.exit_code == 0, result.output
    save_health.assert_called_once_with(rows_sentinel, "30d", _START, _END)
    save_storage.assert_not_called()


def test_data_health_without_save_persists_nothing(monkeypatch):
    _rows, _breakdown, save_health, save_storage = _patch_data_health(monkeypatch)

    result = _runner.invoke(dh.app, ["7d"])

    assert result.exit_code == 0, result.output
    save_health.assert_not_called()
    save_storage.assert_not_called()
