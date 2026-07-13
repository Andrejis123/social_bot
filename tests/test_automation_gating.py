"""Failing-first tests for report-gated archive automation.

Pins four pieces of not-yet-written behavior:

1. `queries.record_report_run` / `queries.has_report_run` over a `report_runs`
   table (client_slug + period_start + period_end; with `platforms` given the
   recorded rows must cover every one — NULL platform = all-platform deck —
   otherwise any row for the exact window passes).
2. `publish_report` records a report run after a successful Supabase upload,
   best-effort: a recording failure must not break publishing.
3. `archive` gains `--require-report`: a client with no recorded report for
   the window is NOT archived (build_bundle never called), Telegram is
   notified with an error mentioning "no successful report", and the run
   exits non-zero. Default (flag off) keeps today's behavior. The per-client
   archive body is exposed as `archive_client(slug, start_dt, end_dt)`.
4. `purge` gains `--empty-ok`: an applied purge with zero candidates exits
   cleanly instead of SystemExit.

The production code does not exist yet, so the module-level imports of the
new symbols make this whole file fail collection with a clean ImportError
until the feature lands. Unit tests only: the in-memory fake Supabase below
(extended from tests/test_archive_purge.py with `insert` support) applies
the real filters; no live Supabase/Drive/Telegram is touched.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import scripts.archive_and_purge as ap
from scripts.archive_and_purge import archive_client
from social_bot.db import queries
from social_bot.db.queries import has_report_run, record_report_run
from social_bot.reports import renderer
from social_bot.reports.data import Period
from social_bot.storage.reports import UploadedReport
from tests.fakes import FakeSupabase as _FakeSB
from tests.fakes import make_bundle as _bundle
from tests.fakes import patch_purge as _patch_purge

# ─────────────────────────────────────────────────────────────────────
# 1. record_report_run / has_report_run
# ─────────────────────────────────────────────────────────────────────


def _report_run_row(**overrides) -> dict:
    row = {
        "client_slug": "agape",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "platform": "instagram",
        "slide_count": 10,
        "bytes_size": 1000,
        "created_at": "2026-07-01T02:00:00+00:00",
    }
    row.update(overrides)
    return row


def test_record_report_run_inserts_row(monkeypatch):
    sb = _FakeSB({"report_runs": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    record_report_run(
        "agape", date(2026, 6, 1), date(2026, 6, 30), "instagram", 42, 12345
    )

    saved = sb.tables["report_runs"]
    assert len(saved) == 1
    row = saved[0]
    assert row["client_slug"] == "agape"
    assert row["period_start"] == "2026-06-01"  # ISO date string
    assert row["period_end"] == "2026-06-30"
    assert row["platform"] == "instagram"
    assert row["slide_count"] == 42
    assert row["bytes_size"] == 12345
    assert row.get("created_at")


def test_record_report_run_platform_none(monkeypatch):
    sb = _FakeSB({"report_runs": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    record_report_run("agape", date(2026, 6, 1), date(2026, 6, 30), None, 5, 1)

    assert sb.tables["report_runs"][0]["platform"] is None


def test_has_report_run_matches_exact_period(monkeypatch):
    sb = _FakeSB({"report_runs": [_report_run_row()]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert has_report_run("agape", date(2026, 6, 1), date(2026, 6, 30)) is True


def test_has_report_run_ignores_platform(monkeypatch):
    """A facebook-only report still counts: the check is client + period."""
    sb = _FakeSB({"report_runs": [_report_run_row(platform="facebook")]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert has_report_run("agape", date(2026, 6, 1), date(2026, 6, 30)) is True


def test_has_report_run_false_on_mismatch(monkeypatch):
    sb = _FakeSB({"report_runs": [_report_run_row()]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    # Different client
    assert has_report_run("ecig", date(2026, 6, 1), date(2026, 6, 30)) is False
    # Shifted start
    assert has_report_run("agape", date(2026, 6, 2), date(2026, 6, 30)) is False
    # Shifted end
    assert has_report_run("agape", date(2026, 6, 1), date(2026, 6, 29)) is False


def test_record_then_has_round_trip(monkeypatch):
    sb = _FakeSB({"report_runs": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert has_report_run("agape", date(2026, 6, 1), date(2026, 6, 30)) is False
    record_report_run("agape", date(2026, 6, 1), date(2026, 6, 30), "instagram", 7, 9)
    assert has_report_run("agape", date(2026, 6, 1), date(2026, 6, 30)) is True


# ─────────────────────────────────────────────────────────────────────
# 1b. per-platform gate: has_report_run(..., platforms=...)
#
# Spec (not yet implemented): `platforms=None`/empty keeps the legacy
# "any row for the exact client + period" behavior. A non-empty set
# passes iff a matching row has platform NULL (an all-platform deck),
# or the matching rows' platform values form a superset of `platforms`.
# ─────────────────────────────────────────────────────────────────────

_JUNE = (date(2026, 6, 1), date(2026, 6, 30))


def test_has_report_run_platforms_missing_one_is_false(monkeypatch):
    """Only an instagram deck landed; requiring instagram+tiktok must fail."""
    sb = _FakeSB({"report_runs": [_report_run_row(platform="instagram")]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert (
        has_report_run("agape", *_JUNE, platforms={"instagram", "tiktok"})
        is False
    )


def test_has_report_run_platforms_all_present_is_true(monkeypatch):
    """One row per required platform (plus an extra) covers the requirement."""
    sb = _FakeSB(
        {
            "report_runs": [
                _report_run_row(platform="instagram"),
                _report_run_row(platform="tiktok"),
                _report_run_row(platform="facebook"),  # superset is fine
            ]
        }
    )
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert (
        has_report_run("agape", *_JUNE, platforms={"instagram", "tiktok"})
        is True
    )


def test_has_report_run_platform_null_row_covers_all(monkeypatch):
    """A platform=NULL row is an all-platform deck and satisfies any set."""
    sb = _FakeSB({"report_runs": [_report_run_row(platform=None)]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert (
        has_report_run("agape", *_JUNE, platforms={"instagram", "tiktok"})
        is True
    )


def test_has_report_run_platforms_none_is_legacy(monkeypatch):
    """Explicit platforms=None: any row for the exact period passes."""
    sb = _FakeSB({"report_runs": [_report_run_row(platform="instagram")]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert has_report_run("agape", *_JUNE, platforms=None) is True


def test_has_report_run_platforms_empty_is_legacy(monkeypatch):
    """An empty set behaves like platforms=None."""
    sb = _FakeSB({"report_runs": [_report_run_row(platform="instagram")]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert has_report_run("agape", *_JUNE, platforms=set()) is True


def test_has_report_run_platforms_wrong_period_is_false(monkeypatch):
    """Even an all-platform row for a different period never satisfies."""
    sb = _FakeSB({"report_runs": [_report_run_row(platform=None)]})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    assert (
        has_report_run(
            "agape",
            date(2026, 5, 1),
            date(2026, 5, 31),
            platforms={"instagram", "tiktok"},
        )
        is False
    )


# ─────────────────────────────────────────────────────────────────────
# 2. publish_report records the run (best-effort)
# ─────────────────────────────────────────────────────────────────────

# Parameter order pinned by the spec'd signature of record_report_run.
_RECORD_PARAMS = (
    "client_slug", "period_start", "period_end",
    "platform", "slide_count", "bytes_size",
)


def _bound_record_call(call: tuple) -> dict:
    """Normalize a (args, kwargs) capture to the spec'd parameter names."""
    args, kwargs = call
    bound = dict(zip(_RECORD_PARAMS, args, strict=False))
    bound.update(kwargs)
    return bound


def _period() -> Period:
    return Period(
        start=datetime(2026, 6, 1, tzinfo=UTC),
        end=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
        label="1 June to 30 June 2026",
    )


def _patch_publish(monkeypatch, tmp_path, record):
    built = SimpleNamespace(
        path=tmp_path / "deck.pptx",
        report=SimpleNamespace(client_name="Agape"),
        slide_count=12,
    )
    uploaded = UploadedReport(
        storage_path="agape/deck.pptx",
        signed_url="https://signed.example/deck",
        bytes_size=54321,
    )
    monkeypatch.setattr(renderer, "_build_report", lambda *a, **k: built)
    monkeypatch.setattr(renderer, "upload_report", lambda slug, p: uploaded)
    monkeypatch.setattr(renderer, "drive", MagicMock())
    monkeypatch.setattr(renderer, "telegram", MagicMock())
    monkeypatch.setattr(renderer.queries, "record_report_run", record)
    return built, uploaded


def test_publish_report_records_run_once(monkeypatch, tmp_path):
    calls: list[tuple] = []
    _built, uploaded = _patch_publish(
        monkeypatch, tmp_path, lambda *a, **k: calls.append((a, k))
    )

    path, up = renderer.publish_report("agape", _period(), platform="instagram")

    assert up is uploaded
    assert len(calls) == 1
    bound = _bound_record_call(calls[0])
    assert bound == {
        "client_slug": "agape",
        "period_start": date(2026, 6, 1),
        "period_end": date(2026, 6, 30),
        "platform": "instagram",
        "slide_count": 12,
        "bytes_size": 54321,
    }


def test_publish_report_recording_failure_is_swallowed(monkeypatch, tmp_path):
    """record_report_run raising must not break the publish return."""
    def boom(*_a, **_k):
        raise RuntimeError("report_runs table missing")

    built, uploaded = _patch_publish(monkeypatch, tmp_path, boom)

    path, up = renderer.publish_report("agape", _period(), platform=None)

    assert path == built.path
    assert up is uploaded


# ─────────────────────────────────────────────────────────────────────
# 3. archive_client + archive --require-report gate
# ─────────────────────────────────────────────────────────────────────




_START_DT = datetime(2026, 5, 1, tzinfo=UTC)
_END_DT = datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)


def _patch_window_platforms(monkeypatch, platforms=("instagram",)):
    """Stub the gate's content-platform lookup — the fake clients in these
    tests have no rows behind queries.list_window_platforms."""
    monkeypatch.setattr(
        ap.queries,
        "list_window_platforms",
        lambda slug, start, end: set(platforms),
        raising=False,
    )


def _patch_archive_happy(monkeypatch, tmp_path):
    bundle = _bundle(tmp_path, ["c/a.jpg", "c/b.jpg"], 0)
    monkeypatch.setattr(ap, "build_bundle", lambda *a: bundle)
    monkeypatch.setattr(
        ap.drive, "upload_bundle", lambda slug, zp: {"id": "d1", "webViewLink": ""}
    )
    monkeypatch.setattr(
        ap.drive, "get_file_size", lambda fid: bundle.zip_path.stat().st_size
    )
    monkeypatch.setattr(ap.telegram, "notify_archive_completed", lambda **kw: None)
    stamp = MagicMock(return_value=2)
    monkeypatch.setattr(ap.queries, "stamp_archived", stamp)
    return bundle, stamp


def test_archive_client_happy_path_stamps(monkeypatch, tmp_path):
    _bundle_obj, stamp = _patch_archive_happy(monkeypatch, tmp_path)

    archive_client("c1", _START_DT, _END_DT)

    stamp.assert_called_once_with(["c/a.jpg", "c/b.jpg"], drive_id="d1")


def test_archive_client_raises_on_incomplete_bundle(monkeypatch, tmp_path):
    """The per-client body raises (does not swallow) so the command can count
    the failure; no upload, no stamp."""
    monkeypatch.setattr(
        ap, "build_bundle", lambda *a: _bundle(tmp_path, ["c/a.jpg"], 1)
    )
    upload = MagicMock()
    stamp = MagicMock()
    monkeypatch.setattr(ap.drive, "upload_bundle", upload)
    monkeypatch.setattr(ap.queries, "stamp_archived", stamp)

    with pytest.raises(Exception):  # noqa: B017 - contract is "raises on failure"
        archive_client("c1", _START_DT, _END_DT)

    upload.assert_not_called()
    stamp.assert_not_called()


def test_archive_require_report_blocks_unreported_client(monkeypatch):
    """No recorded report for the window: client is NOT archived, Telegram is
    told why, and the run fails."""
    build = MagicMock()
    monkeypatch.setattr(ap, "build_bundle", build)
    notified: dict = {}
    monkeypatch.setattr(
        ap.telegram, "notify_archive_failed", lambda **kw: notified.update(kw)
    )
    _patch_window_platforms(monkeypatch)
    gate_calls: list[tuple] = []

    def has_run(slug, start, end, platforms=None):
        gate_calls.append((slug, start, end, platforms))
        return False

    monkeypatch.setattr(ap.queries, "has_report_run", has_run, raising=False)

    with pytest.raises(SystemExit):
        ap.archive("2026-05-01", "2026-05-31", ["c1"], require_report=True)

    build.assert_not_called()
    assert gate_calls == [
        ("c1", date(2026, 5, 1), date(2026, 5, 31), {"instagram"})
    ]
    assert notified["client_slug"] == "c1"
    assert "no successful report" in notified["error"]


def test_archive_require_report_passes_reported_client(monkeypatch, tmp_path):
    _bundle_obj, stamp = _patch_archive_happy(monkeypatch, tmp_path)
    _patch_window_platforms(monkeypatch)
    monkeypatch.setattr(
        ap.queries, "has_report_run", lambda *a, **kw: True, raising=False
    )

    ap.archive("2026-05-01", "2026-05-31", ["c1"], require_report=True)

    stamp.assert_called_once_with(["c/a.jpg", "c/b.jpg"], drive_id="d1")


def test_archive_without_flag_skips_gate(monkeypatch, tmp_path):
    """Default CLI invocation (no --require-report) never consults
    has_report_run and archives as today."""
    _bundle_obj, stamp = _patch_archive_happy(monkeypatch, tmp_path)
    gate = MagicMock(return_value=False)
    monkeypatch.setattr(ap.queries, "has_report_run", gate, raising=False)

    result = CliRunner().invoke(
        ap.app, ["archive", "2026-05-01", "2026-05-31", "c1"]
    )

    assert result.exit_code == 0, result.output
    gate.assert_not_called()
    stamp.assert_called_once()


# ─────────────────────────────────────────────────────────────────────
# 4. purge --empty-ok
# ─────────────────────────────────────────────────────────────────────


def test_purge_apply_empty_ok_exits_cleanly(monkeypatch, capsys):
    calls = _patch_purge(monkeypatch, [])
    tg = MagicMock()
    monkeypatch.setattr(ap, "telegram", tg)

    ap.purge(grace_days=7, client=None, apply=True, empty_ok=True)  # no SystemExit

    assert calls["removed"] is None
    assert calls["tombstoned"] is None
    assert not tg.method_calls  # nothing notified for a clean empty run
    assert capsys.readouterr().out.strip()  # a human-readable note is printed


def test_purge_apply_empty_without_flag_still_aborts(monkeypatch):
    calls = _patch_purge(monkeypatch, [])

    with pytest.raises(SystemExit):
        ap.purge(grace_days=7, client=None, apply=True, empty_ok=False)

    assert calls["removed"] is None
    assert calls["tombstoned"] is None


def test_purge_apply_empty_ok_with_candidates_unchanged(monkeypatch):
    candidates = [
        {"id": "A", "kind": "post", "item_id": "P1",
         "storage_path": "c/a.jpg", "table": "media"},
        {"id": "S", "kind": "story", "item_id": "S1",
         "storage_path": "c/s.mp4", "table": "story_media"},
    ]
    calls = _patch_purge(monkeypatch, candidates)
    monkeypatch.setattr(ap, "telegram", MagicMock())

    ap.purge(grace_days=7, client=None, apply=True, empty_ok=True)

    assert calls["removed"] == ["c/a.jpg", "c/s.mp4"]
    assert calls["tombstoned"] == ["c/a.jpg", "c/s.mp4"]
