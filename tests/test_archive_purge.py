"""Tests for the Supabase Storage archive/purge feature.

The data-loss-critical invariant: the gated purge tombstones ONLY rows proven to
live inside a verified Drive bundle (archived_at set) AND past the grace window.
Media never archived, skipped during bundling, within grace, or already
tombstoned MUST survive `purge --apply`.

These are unit tests. A small in-memory fake Supabase actually applies the
filters the production queries build, so the invariant is exercised for real
rather than asserted against a call chain. No live Supabase/Drive/API is touched.
"""
from __future__ import annotations

import threading
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import scripts.archive_and_purge as ap
import scripts.make_content_bundle as mcb
import scripts.restore_from_bundle as rfb
from scripts.make_content_bundle import BundleResult
from social_bot.db import queries
from tests.fakes import FakeSupabase as _FakeSB
from tests.fakes import patch_purge as _patch_purge

# In-memory fake Supabase: shared helper in tests/fakes.py (one copy of the
# query-builder semantics for all test files).


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def now():
    return datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _patch_bundle_queries(monkeypatch, tmp_path, media_paths):
    """Patch DEFAULT_OUT_DIR + the queries build_bundle calls; return (start, end).

    Only list_media_for_posts varies between bundle tests (the `media_paths`
    storage paths); everything else is fixed: one client, one account, one post,
    no stories.
    """
    monkeypatch.setattr(mcb, "DEFAULT_OUT_DIR", tmp_path)
    monkeypatch.setattr(mcb.queries, "get_client_id_by_slug", lambda s: "client-1")
    monkeypatch.setattr(
        mcb.queries, "list_accounts_for_client", lambda cid: [{"id": "acc-1"}]
    )
    monkeypatch.setattr(mcb.queries, "list_posts_in_period", lambda *a: [{"id": "post-1"}])
    monkeypatch.setattr(mcb.queries, "list_stories_in_period", lambda *a: [])
    monkeypatch.setattr(
        mcb.queries,
        "list_media_for_posts",
        lambda ids: [{"storage_path": p} for p in media_paths],
    )
    monkeypatch.setattr(mcb.queries, "list_story_media_for_stories", lambda ids: [])
    return (
        datetime(2026, 5, 1, tzinfo=UTC),
        datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC),
    )


# ─────────────────────────────────────────────────────────────────────
# 1. build_bundle excludes skipped (failed) downloads from written_paths
# ─────────────────────────────────────────────────────────────────────


def test_build_bundle_excludes_skipped(monkeypatch, tmp_path):
    start, end = _patch_bundle_queries(
        monkeypatch, tmp_path, ["c/good1.jpg", "c/skipped.jpg", "c/good2.jpg"]
    )

    def fake_download(path):
        if path == "c/skipped.jpg":
            raise RuntimeError("download failed")
        return (b"x" * 10, "image/jpeg")

    monkeypatch.setattr(mcb, "download_from_storage", fake_download)

    result = mcb.build_bundle("test-client", start, end)

    assert set(result.written_paths) == {"c/good1.jpg", "c/good2.jpg"}
    assert "c/skipped.jpg" not in result.written_paths
    assert result.skipped == 1
    assert result.zip_path.exists()


def test_safe_download_returns_none_on_failure(monkeypatch):
    """_safe_download surfaces an exhausted download as None (retry lives below)."""
    def fail(_path):
        raise RuntimeError("The read operation timed out")

    monkeypatch.setattr(mcb, "download_from_storage", fail)
    assert mcb._safe_download("c/x.jpg") is None


def test_build_bundle_streams_without_materializing_whole_period(monkeypatch, tmp_path):
    """build_bundle must NOT hold every period blob resident at once.

    Root cause of the OOM: `blobs = list(ex.map(_safe_download, paths))` buffers
    every downloaded object into one list before the zip is written, so peak
    memory scales with the whole period (223 files / ~636MB on ecig June ->
    SIGKILL on the 961MB droplet). The fix bounds resident blobs to a sliding
    window of ~2 * _DOWNLOAD_WORKERS: each blob is written into the zip and
    discarded before the window advances.

    We instrument the two ends of a blob's lifetime:
      * a successful download increments a shared "resident" counter (and peak),
      * writing it into the zip (`writestr`) decrements it — the consumption
        point in both the current and streamed implementations.
    A failed download holds nothing, so it neither increments nor is written.
    """
    n_paths = 40
    failing = {"c/skipped.jpg"}
    paths = [f"c/media_{i}.jpg" for i in range(n_paths - 1)]
    paths.insert(n_paths // 2, "c/skipped.jpg")  # one failure in the middle
    assert len(paths) == n_paths

    start, end = _patch_bundle_queries(monkeypatch, tmp_path, paths)

    lock = threading.Lock()
    state = {"resident": 0, "peak": 0}

    def tracking_download(path):
        if path in failing:
            raise RuntimeError("download failed")
        with lock:
            state["resident"] += 1
            state["peak"] = max(state["peak"], state["resident"])
        return (b"x" * 100, "image/jpeg")

    monkeypatch.setattr(mcb, "download_from_storage", tracking_download)

    orig_writestr = zipfile.ZipFile.writestr

    def tracking_writestr(self, zinfo_or_arcname, data, *a, **k):
        with lock:
            state["resident"] -= 1
        return orig_writestr(self, zinfo_or_arcname, data, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", tracking_writestr)

    result = mcb.build_bundle("test-client", start, end)

    bound = 2 * mcb._DOWNLOAD_WORKERS
    # Memory invariant: never buffer the whole period.
    assert state["peak"] < n_paths, (
        f"build_bundle materialized {state['peak']} of {n_paths} blobs at once "
        "(whole-period buffering -> OOM)"
    )
    assert state["peak"] <= bound, (
        f"peak resident blobs {state['peak']} exceeds bounded window {bound} "
        f"(2 * _DOWNLOAD_WORKERS)"
    )
    # All-or-nothing: the failed download is counted and never written.
    assert result.skipped == 1
    assert "c/skipped.jpg" not in result.written_paths
    assert len(result.written_paths) == n_paths - 1


# ─────────────────────────────────────────────────────────────────────
# download_from_storage retry (root-cause fix for unretried read timeouts)
# ─────────────────────────────────────────────────────────────────────


def _fake_sb_download(side_effects):
    """Build a fake Supabase client whose .storage...download() pops side_effects
    (an Exception is raised, bytes are returned)."""
    seq = list(side_effects)

    class Bucket:
        def download(self, _path):
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

    class Storage:
        def from_(self, _b):
            return Bucket()

    return SimpleNamespace(storage=Storage())


def test_download_from_storage_retries_then_succeeds(monkeypatch):
    import social_bot.storage.media as media
    monkeypatch.setattr(media, "_DOWNLOAD_BACKOFF_S", 0)
    monkeypatch.setattr(media, "get_settings",
                        lambda: SimpleNamespace(supabase_media_bucket="media"))
    sb = _fake_sb_download([
        TimeoutError("The read operation timed out"),
        TimeoutError("The read operation timed out"),
        b"the-bytes",
    ])
    monkeypatch.setattr(media, "get_supabase", lambda: sb)

    data, mime = media.download_from_storage("c/h/instagram/posts/2026/06/x/0.jpg")
    assert data == b"the-bytes"
    assert mime == "image/jpeg"


def test_download_from_storage_raises_after_exhausting_retries(monkeypatch):
    import social_bot.storage.media as media
    monkeypatch.setattr(media, "_DOWNLOAD_BACKOFF_S", 0)
    monkeypatch.setattr(media, "_DOWNLOAD_RETRIES", 3)
    monkeypatch.setattr(media, "get_settings",
                        lambda: SimpleNamespace(supabase_media_bucket="media"))
    sb = _fake_sb_download([TimeoutError("timed out")] * 3)
    monkeypatch.setattr(media, "get_supabase", lambda: sb)

    with pytest.raises(TimeoutError):
        media.download_from_storage("c/x.jpg")


# ─────────────────────────────────────────────────────────────────────
# 2. stamp_archived: only written paths, idempotent, skipped never stamped
# ─────────────────────────────────────────────────────────────────────


def test_stamp_archived_only_unarchived_written_paths(monkeypatch):
    rows = [
        {"id": "m1", "storage_path": "c/good1.jpg", "archived_at": None,
         "archive_drive_id": None},
        {"id": "m2", "storage_path": "c/skipped.jpg", "archived_at": None,
         "archive_drive_id": None},
    ]
    sb = _FakeSB({"media": rows, "story_media": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    # Only the verified-written path is passed in; the skipped one is not.
    stamped = queries.stamp_archived(["c/good1.jpg"], drive_id="drive-xyz")

    assert stamped == 1
    assert rows[0]["archived_at"] is not None
    assert rows[0]["archive_drive_id"] == "drive-xyz"
    # The skipped row was never passed in, so it stays unarchived forever.
    assert rows[1]["archived_at"] is None


def test_stamp_archived_is_idempotent(monkeypatch):
    """A re-run must not move archived_at (the IS NULL guard)."""
    first_stamp = _iso(datetime(2026, 6, 1, tzinfo=UTC))
    rows = [
        {"id": "m1", "storage_path": "c/good1.jpg", "archived_at": first_stamp,
         "archive_drive_id": "drive-old"},
    ]
    sb = _FakeSB({"media": rows, "story_media": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    stamped = queries.stamp_archived(["c/good1.jpg"], drive_id="drive-new")

    assert stamped == 0  # already archived -> guard excludes it
    assert rows[0]["archived_at"] == first_stamp  # unchanged
    assert rows[0]["archive_drive_id"] == "drive-old"


# ─────────────────────────────────────────────────────────────────────
# 3. list_archived_purgeable: archived + grace-expired + bytes present only
# ─────────────────────────────────────────────────────────────────────


def test_list_archived_purgeable_selects_only_eligible(monkeypatch, now):
    old = _iso(now - timedelta(days=30))      # archived long ago
    recent = _iso(now - timedelta(days=2))    # within grace
    media = [
        {"id": "A", "storage_path": "c/a.jpg", "archived_at": old,
         "archive_drive_id": "d"},                                  # eligible
        {"id": "B", "storage_path": "c/b.jpg", "archived_at": None,
         "archive_drive_id": None},                                 # never archived
        {"id": "C", "storage_path": "c/c.jpg", "archived_at": recent,
         "archive_drive_id": "d"},                                  # within grace
        {"id": "D", "storage_path": None, "archived_at": old,
         "archive_drive_id": "d"},                                  # already tombstoned
    ]
    sb = _FakeSB({"media": media, "story_media": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    cutoff = now - timedelta(days=7)
    out = queries.list_archived_purgeable(cutoff)

    assert [r["id"] for r in out] == ["A"]
    assert out[0]["table"] == "media"


def test_list_archived_purgeable_spans_both_tables(monkeypatch, now):
    old = _iso(now - timedelta(days=30))
    sb = _FakeSB({
        "media": [{"id": "A", "storage_path": "c/posts/a.jpg", "archived_at": old,
                   "archive_drive_id": "d"}],
        "story_media": [{"id": "S", "storage_path": "c/stories/s.mp4",
                         "archived_at": old, "archive_drive_id": "d"}],
    })
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    out = queries.list_archived_purgeable(now - timedelta(days=7))
    by_table = {r["table"]: r["id"] for r in out}
    assert by_table == {"media": "A", "story_media": "S"}


# ─────────────────────────────────────────────────────────────────────
# 4. purge command: dry-run vs --apply vs empty-set abort
# ─────────────────────────────────────────────────────────────────────


def test_purge_dry_run_deletes_nothing(monkeypatch):
    candidates = [{"id": "A", "storage_path": "c/a.jpg", "table": "media"}]
    calls = _patch_purge(monkeypatch, candidates)

    ap.purge(grace_days=7, client=None, apply=False)

    assert calls["removed"] is None
    assert calls["tombstoned"] is None


def test_purge_apply_deletes_exactly_candidates(monkeypatch):
    candidates = [
        {"id": "A", "storage_path": "c/a.jpg", "table": "media"},
        {"id": "S", "storage_path": "c/s.mp4", "table": "story_media"},
    ]
    calls = _patch_purge(monkeypatch, candidates)

    ap.purge(grace_days=7, client=None, apply=True)

    assert calls["removed"] == ["c/a.jpg", "c/s.mp4"]
    assert calls["tombstoned"] == ["c/a.jpg", "c/s.mp4"]


def test_purge_apply_aborts_on_empty(monkeypatch):
    calls = _patch_purge(monkeypatch, [])

    with pytest.raises(SystemExit):
        ap.purge(grace_days=7, client=None, apply=True)

    assert calls["removed"] is None
    assert calls["tombstoned"] is None


def test_purge_client_filter_scopes_to_one_client(monkeypatch):
    """--client purges only that client's paths, leaving others (e.g. a stamped
    client mid-grace) untouched. This is what lets us purge agape while
    iluminatecz waits out its 7-day grace."""
    candidates = [
        {"id": "A", "storage_path": "agape/h/instagram/posts/x.jpg", "table": "media"},
        {"id": "I", "storage_path": "iluminatecz/h/instagram/posts/y.jpg", "table": "media"},
    ]
    calls = _patch_purge(monkeypatch, candidates)

    ap.purge(grace_days=0, client="agape", apply=True)

    assert calls["removed"] == ["agape/h/instagram/posts/x.jpg"]
    assert calls["tombstoned"] == ["agape/h/instagram/posts/x.jpg"]


# ─────────────────────────────────────────────────────────────────────
# 5. archive command: all-or-nothing (fail closed on any skip / size mismatch)
# ─────────────────────────────────────────────────────────────────────


def _bundle(tmp_path, written, skipped) -> BundleResult:
    zp = tmp_path / "b.zip"
    zp.write_bytes(b"x" * 100)
    return BundleResult(
        zip_path=zp, written_paths=list(written), skipped=skipped, total_bytes=100
    )


def test_archive_aborts_on_incomplete_bundle(monkeypatch, tmp_path):
    """Any skipped file -> no upload, no stamp, run fails (all-or-nothing)."""
    monkeypatch.setattr(ap, "build_bundle", lambda *a: _bundle(tmp_path, ["c/a.jpg"], 1))
    upload = MagicMock()
    stamp = MagicMock()
    monkeypatch.setattr(ap.drive, "upload_bundle", upload)
    monkeypatch.setattr(ap.queries, "stamp_archived", stamp)

    with pytest.raises(SystemExit):
        ap.archive("2026-05-01", "2026-05-31", ["c1"])

    upload.assert_not_called()
    stamp.assert_not_called()


def test_archive_happy_path_verifies_then_stamps(monkeypatch, tmp_path):
    bundle = _bundle(tmp_path, ["c/a.jpg", "c/b.jpg"], 0)
    monkeypatch.setattr(ap, "build_bundle", lambda *a: bundle)
    monkeypatch.setattr(
        ap.drive, "upload_bundle", lambda slug, zp: {"id": "d1", "webViewLink": ""}
    )
    monkeypatch.setattr(
        ap.drive, "get_file_size", lambda fid: bundle.zip_path.stat().st_size
    )
    stamp = MagicMock(return_value=2)
    monkeypatch.setattr(ap.queries, "stamp_archived", stamp)

    ap.archive("2026-05-01", "2026-05-31", ["c1"])

    stamp.assert_called_once_with(["c/a.jpg", "c/b.jpg"], drive_id="d1")


def test_archive_aborts_on_size_mismatch(monkeypatch, tmp_path):
    """A truncated/corrupt upload (size mismatch) must not stamp anything."""
    bundle = _bundle(tmp_path, ["c/a.jpg"], 0)
    monkeypatch.setattr(ap, "build_bundle", lambda *a: bundle)
    monkeypatch.setattr(
        ap.drive, "upload_bundle", lambda slug, zp: {"id": "d1", "webViewLink": ""}
    )
    monkeypatch.setattr(ap.drive, "get_file_size", lambda fid: 999_999)  # != local
    stamp = MagicMock()
    monkeypatch.setattr(ap.queries, "stamp_archived", stamp)

    with pytest.raises(SystemExit):
        ap.archive("2026-05-01", "2026-05-31", ["c1"])

    stamp.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# THE invariant: skipped media never reaches the purge (end-to-end at unit level)
# ─────────────────────────────────────────────────────────────────────


def test_skipped_media_survives_purge(monkeypatch, now):
    """A file skipped during bundling is never stamped, never purgeable, never
    deleted. This is the regression guard against deleting un-archived media."""
    media = [
        {"id": "good", "storage_path": "c/good.jpg", "archived_at": None,
         "archive_drive_id": None},
        {"id": "skipped", "storage_path": "c/skipped.jpg", "archived_at": None,
         "archive_drive_id": None},
    ]
    sb = _FakeSB({"media": media, "story_media": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    # Bundle verified only "c/good.jpg" (skipped excluded from written_paths).
    written_paths = ["c/good.jpg"]
    queries.stamp_archived(written_paths, drive_id="drive-1")

    # Backdate the stamp so it clears the grace window.
    for r in media:
        if r["archived_at"] is not None:
            r["archived_at"] = _iso(now - timedelta(days=30))

    purgeable = queries.list_archived_purgeable(now - timedelta(days=7))
    purge_paths = [r["storage_path"] for r in purgeable]

    assert purge_paths == ["c/good.jpg"]
    assert "c/skipped.jpg" not in purge_paths
    # The skipped row keeps its bytes (storage_path intact, never tombstoned).
    assert media[1]["storage_path"] == "c/skipped.jpg"
    assert media[1]["archived_at"] is None


# ─────────────────────────────────────────────────────────────────────
# Report driver: a failed client is notified to Telegram, not just logged
# ─────────────────────────────────────────────────────────────────────


def test_report_failure_notifies_telegram(monkeypatch):
    import scripts.run_monthly_reports as rmr

    def publish(slug, _period, **_kw):
        if slug == "ecig-monitoring":
            raise RuntimeError("The read operation timed out")
        return ("x.pptx", SimpleNamespace(signed_url="u"))

    notified: dict = {}
    monkeypatch.setattr(rmr, "publish_report", publish)
    monkeypatch.setattr(
        rmr.telegram, "notify_report_failed", lambda **kw: notified.update(kw)
    )

    with pytest.raises(SystemExit):  # one client failed
        rmr.main(
            "2026-06-01", "2026-06-30", ["agape", "ecig-monitoring"],
            platform="instagram", reuse_synthesis=False,
        )

    assert notified["client_slug"] == "ecig-monitoring"
    assert "timed out" in notified["error"]


# ─────────────────────────────────────────────────────────────────────
# Restore from bundle: arcname parsing + un-tombstone + full round trip
# ─────────────────────────────────────────────────────────────────────


def test_parse_arcname_post():
    p = rfb._parse_arcname("agape", "h/instagram/posts/2026/06/POST1/3.jpg")
    assert p is not None
    assert p.kind == "post" and p.post_id == "POST1" and p.slide_index == 3
    assert p.storage_path == "agape/h/instagram/posts/2026/06/POST1/3.jpg"


def test_parse_arcname_story():
    p = rfb._parse_arcname("agape", "h/instagram/stories/2026/06/19/STORY1.mp4")
    assert p is not None
    assert p.kind == "story" and p.story_id == "STORY1"
    assert p.storage_path == "agape/h/instagram/stories/2026/06/19/STORY1.mp4"


def test_parse_arcname_rejects_traversal():
    assert rfb._parse_arcname("agape", "h/instagram/posts/../../../etc/0.jpg") is None
    assert rfb._parse_arcname("agape", "/abs/instagram/posts/2026/06/P/0.jpg") is None


def test_restore_media_row_untombstones(monkeypatch):
    row = {"id": "m1", "post_id": "P1", "slide_index": 0, "storage_path": None,
           "archived_at": "2026-06-01T00:00:00+00:00", "archive_drive_id": "D"}
    sb = _FakeSB({"media": [row], "story_media": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    n = queries.restore_media_row(
        post_id="P1", slide_index=0, drive_id="D", storage_path="agape/x/0.jpg"
    )
    assert n == 1
    assert row["storage_path"] == "agape/x/0.jpg"
    assert row["archived_at"] is None
    assert row["archive_drive_id"] is None


def test_restore_guard_skips_live_row(monkeypatch):
    """A still-present row (storage_path not NULL) must not be touched."""
    row = {"id": "m1", "post_id": "P1", "slide_index": 0,
           "storage_path": "agape/live.jpg",
           "archived_at": "2026-06-01T00:00:00+00:00", "archive_drive_id": "D"}
    sb = _FakeSB({"media": [row], "story_media": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    n = queries.restore_media_row(
        post_id="P1", slide_index=0, drive_id="D", storage_path="x"
    )
    assert n == 0
    assert row["storage_path"] == "agape/live.jpg"  # untouched


def test_archive_purge_restore_round_trip(monkeypatch):
    """Full cycle: stamp -> tombstone -> restore returns the row to live."""
    path = "agape/h/instagram/posts/2026/06/P1/0.jpg"
    row = {"id": "m1", "post_id": "P1", "slide_index": 0, "storage_path": path,
           "archived_at": None, "archive_drive_id": None}
    sb = _FakeSB({"media": [row], "story_media": []})
    monkeypatch.setattr(queries, "get_supabase", lambda: sb)

    queries.stamp_archived([path], drive_id="D")
    assert row["archived_at"] is not None
    queries.tombstone_archived([path])
    assert row["storage_path"] is None

    n = queries.restore_media_row(
        post_id="P1", slide_index=0, drive_id="D", storage_path=path
    )
    assert n == 1
    assert row["storage_path"] == path
    assert row["archived_at"] is None
    assert row["archive_drive_id"] is None
