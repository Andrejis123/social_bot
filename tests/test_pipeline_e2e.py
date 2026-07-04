"""
Mocked end-to-end pipeline tests.

Every external (scraper, Supabase via db.queries, media up/download, Gemini
classify, Telegram, Drive) is faked at its module boundary, so these run
offline and instantly. They lock the *orchestration*: dedupe branching, AI
gating, per-item error isolation, and the publish fan-out — the wiring that
unit tests on individual functions don't exercise.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from social_bot.ai.providers.gemini import ClassifyResult
from social_bot.scrapers.base import ScrapedMedia, ScrapedPost, ScrapedStory

# =====================================================================
# ingest_posts
# =====================================================================


def _post(pid: str, *, media_count: int = 1) -> ScrapedPost:
    return ScrapedPost(
        platform="instagram",
        platform_post_id=pid,
        post_type="image",
        caption="a caption",
        permalink=f"https://instagram.com/p/{pid}/",
        posted_at=datetime(2026, 4, 1, tzinfo=UTC),
        media=[
            ScrapedMedia(slide_index=i, media_type="image", source_url=f"https://cdn/{pid}-{i}.jpg")
            for i in range(media_count)
        ],
        like_count=5,
        comment_count=1,
        raw={"id": pid},
    )


class _FakeScraper:
    discovered_platform_account_id = "pk-123"

    def __init__(self, posts: list[ScrapedPost]):
        self._posts = posts

    def scrape_posts(self, handle, **kwargs):
        return self._posts


def _patch_ingest(monkeypatch, *, posts, existing_ids=frozenset(), classify_raises=False):
    """Fake the whole ingest_posts external surface. Returns a call recorder."""
    import social_bot.ai.classifier as classifier_mod
    import social_bot.notifications.telegram as telegram_mod
    from social_bot.db import queries
    from social_bot.pipeline import ingest_posts as ip

    rec: dict[str, list] = defaultdict(list)

    def _record(name, ret=None):
        def fn(*args, **kwargs):
            rec[name].append((args, kwargs))
            return ret
        return fn

    # db.queries — patched on the shared module object (ingest_posts AND
    # run_context both reference it).
    monkeypatch.setattr(queries, "start_run", _record("start_run", "run-1"))
    monkeypatch.setattr(queries, "finish_run", _record("finish_run"))
    monkeypatch.setattr(queries, "record_item_error", _record("record_item_error"))
    monkeypatch.setattr(queries, "upsert_client", _record("upsert_client", "client-1"))
    monkeypatch.setattr(
        queries, "upsert_account",
        _record("upsert_account", {"id": "acct-1", "platform_account_id": None}),
    )
    monkeypatch.setattr(
        queries, "find_post",
        lambda platform, pid: ({"id": f"existing-{pid}"} if pid in existing_ids else None),
    )
    monkeypatch.setattr(queries, "insert_post", _record("insert_post", "post-1"))
    monkeypatch.setattr(queries, "insert_media", _record("insert_media"))
    monkeypatch.setattr(queries, "append_post_metrics", _record("append_post_metrics"))
    monkeypatch.setattr(queries, "update_post_ai", _record("update_post_ai"))
    monkeypatch.setattr(
        queries, "increment_post_ai_attempts", _record("increment_post_ai_attempts")
    )
    monkeypatch.setattr(queries, "set_account_platform_id", _record("set_account_platform_id"))

    # media up/download
    monkeypatch.setattr(
        ip, "download_and_upload",
        lambda **kwargs: SimpleNamespace(storage_path="bucket/path.jpg", bytes_size=42),
    )

    # scraper + client config
    monkeypatch.setattr(ip, "get_scraper", lambda platform: _FakeScraper(posts))
    account = SimpleNamespace(platform="instagram", handle="testhandle", is_owned=True)
    loaded = SimpleNamespace(
        slug="testclient",
        name="Test Client",
        active_accounts=[account],
        config=SimpleNamespace(accounts=[account], ai=SimpleNamespace(prompt_version="v1")),
    )
    monkeypatch.setattr(ip, "load_client", lambda slug: loaded)

    # AI classify (lazy-imported from the classifier module)
    def _classify(*, post, loaded_client):
        if classify_raises:
            raise RuntimeError("gemini down")
        return ClassifyResult(category="News", confidence=0.9, reasoning="r")
    monkeypatch.setattr(classifier_mod, "classify", _classify)

    # silence Telegram + the 1.5s AI throttle
    monkeypatch.setattr(telegram_mod, "send", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)

    return rec


def test_ingest_new_and_existing_posts(monkeypatch):
    from social_bot.pipeline.ingest_posts import ingest_posts_for_client

    rec = _patch_ingest(
        monkeypatch,
        posts=[_post("100"), _post("200")],
        existing_ids={"200"},  # 200 already in DB → metrics-only path
    )
    run_ids = ingest_posts_for_client("testclient")

    assert run_ids == ["run-1"]
    assert len(rec["insert_post"]) == 1          # only the new post inserted
    assert len(rec["insert_media"]) == 1         # its single media row
    assert len(rec["append_post_metrics"]) == 2  # both posts get a metrics snapshot
    assert len(rec["update_post_ai"]) == 1       # classified the new post only
    # discovered pk differed from cached None → persisted
    assert len(rec["set_account_platform_id"]) == 1
    # clean run
    assert rec["finish_run"][0][1]["status"] == "success"
    assert rec["finish_run"][0][1]["items_new"] == 1
    assert rec["finish_run"][0][1]["items_updated"] == 1


def test_ingest_isolates_classify_failure(monkeypatch):
    from social_bot.pipeline.ingest_posts import ingest_posts_for_client

    rec = _patch_ingest(monkeypatch, posts=[_post("100")], classify_raises=True)
    run_ids = ingest_posts_for_client("testclient")

    assert run_ids == ["run-1"]
    # The post + media + metrics are persisted before classify runs, so an AI
    # failure must not lose them.
    assert len(rec["insert_post"]) == 1
    assert len(rec["append_post_metrics"]) == 1
    assert len(rec["update_post_ai"]) == 0
    assert len(rec["increment_post_ai_attempts"]) == 1
    # one item failed (AI) but one item succeeded → partial, not failed
    assert rec["finish_run"][0][1]["status"] == "partial"


def test_ingest_skips_unsupported_platforms(monkeypatch):
    from social_bot.pipeline import ingest_posts as ip
    from social_bot.pipeline.ingest_posts import ingest_posts_for_client

    _patch_ingest(monkeypatch, posts=[_post("100")])
    # A platform with no registered scraper (instagram + facebook are supported).
    yt = SimpleNamespace(platform="youtube", handle="somechannel", is_owned=True)
    loaded = SimpleNamespace(
        slug="testclient", name="Test Client", active_accounts=[yt],
        config=SimpleNamespace(accounts=[yt], ai=SimpleNamespace(prompt_version="v1")),
    )
    monkeypatch.setattr(ip, "load_client", lambda slug: loaded)

    run_ids = ingest_posts_for_client("testclient")
    assert run_ids == []  # unsupported platform ignored, not an error


def test_platform_filter_selects_one_platform(monkeypatch):
    from social_bot.pipeline import ingest_posts as ip
    from social_bot.pipeline.ingest_posts import ingest_posts_for_client

    _patch_ingest(monkeypatch, posts=[_post("100")])
    # Same handle on two platforms (the real agapeslovensko IG+FB case).
    ig = SimpleNamespace(platform="instagram", handle="dup", is_owned=True)
    fb = SimpleNamespace(platform="facebook", handle="dup", is_owned=True)
    loaded = SimpleNamespace(
        slug="testclient", name="Test Client", active_accounts=[ig, fb],
        config=SimpleNamespace(accounts=[ig, fb], ai=SimpleNamespace(prompt_version="v1")),
    )
    monkeypatch.setattr(ip, "load_client", lambda slug: loaded)

    # Without --platform, the shared handle is ambiguous and must fail loudly
    # (silently scraping both platforms caused the agape FB failure loop).
    with pytest.raises(ValueError, match="dup"):
        ingest_posts_for_client("testclient", account_handle="dup")
    # --platform narrows to just the facebook account.
    run_ids = ingest_posts_for_client("testclient", account_handle="dup", platform="facebook")
    assert len(run_ids) == 1


# =====================================================================
# ingest_stories
#
# Near-identical to ingest_posts, but stories diverge in three ways the
# orchestration must honor:
#   * existing story -> skip entirely (no metrics path; stories don't update)
#   * Instagram-only (an active facebook account is skipped, not an error)
#   * media download is per-item isolated -> a 403 (signed-URL expiry) on one
#     media must not lose the story row.
# =====================================================================


def _story(sid: str, *, media_count: int = 1, with_source: bool = True) -> ScrapedStory:
    return ScrapedStory(
        platform="instagram",
        platform_story_id=sid,
        posted_at=datetime(2026, 4, 1, tzinfo=UTC),
        expires_at=datetime(2026, 4, 2, tzinfo=UTC),
        caption="a story caption",
        media=[
            ScrapedMedia(
                slide_index=i,
                media_type="image",
                source_url=(f"https://cdn/{sid}-{i}.jpg" if with_source else ""),
            )
            for i in range(media_count)
        ],
        raw={"id": sid},
    )


class _FakeStoryScraper:
    discovered_platform_account_id = "pk-123"

    def __init__(self, stories: list[ScrapedStory]):
        self._stories = stories

    def scrape_stories(self, handle, **kwargs):
        return self._stories


def _patch_ingest_stories(
    monkeypatch,
    *,
    stories,
    existing_ids=frozenset(),
    classify_raises=False,
    classify_returns_none=False,
    download_raises=False,
):
    """Fake the whole ingest_stories external surface. Returns a call recorder."""
    import social_bot.ai.classifier as classifier_mod
    import social_bot.notifications.telegram as telegram_mod
    from social_bot.db import queries
    from social_bot.pipeline import ingest_stories as ist

    rec: dict[str, list] = defaultdict(list)

    def _record(name, ret=None):
        def fn(*args, **kwargs):
            rec[name].append((args, kwargs))
            return ret
        return fn

    # db.queries — shared module object (ingest_stories AND run_context).
    monkeypatch.setattr(queries, "start_run", _record("start_run", "run-1"))
    monkeypatch.setattr(queries, "finish_run", _record("finish_run"))
    monkeypatch.setattr(queries, "record_item_error", _record("record_item_error"))
    monkeypatch.setattr(queries, "upsert_client", _record("upsert_client", "client-1"))
    monkeypatch.setattr(
        queries, "upsert_account",
        _record("upsert_account", {"id": "acct-1", "platform_account_id": None}),
    )
    monkeypatch.setattr(
        queries, "find_story",
        lambda platform, sid: ({"id": f"existing-{sid}"} if sid in existing_ids else None),
    )
    monkeypatch.setattr(queries, "insert_story", _record("insert_story", "story-1"))
    monkeypatch.setattr(queries, "update_story_ai", _record("update_story_ai"))
    monkeypatch.setattr(
        queries, "increment_story_ai_attempts", _record("increment_story_ai_attempts")
    )
    monkeypatch.setattr(queries, "set_account_platform_id", _record("set_account_platform_id"))

    # media download+upload boundary (httpx GET + Supabase upload + insert_story_media
    # all live behind _download_and_record; stub it whole like posts stub
    # download_and_upload).
    def _download(**kwargs):
        rec["download_and_record"].append(((), kwargs))
        # mimics a 403 on an expired signed URL surfacing from httpx, only on the
        # first media — proves the per-media loop continues to the next one.
        if download_raises and len(rec["download_and_record"]) == 1:
            raise RuntimeError("403 Forbidden")
    monkeypatch.setattr(ist, "_download_and_record", _download)

    # scraper + client config
    monkeypatch.setattr(ist, "get_scraper", lambda platform: _FakeStoryScraper(stories))
    account = SimpleNamespace(platform="instagram", handle="testhandle", is_owned=True)
    loaded = SimpleNamespace(
        slug="testclient",
        name="Test Client",
        active_accounts=[account],
        config=SimpleNamespace(accounts=[account], ai=SimpleNamespace(prompt_version="v1")),
    )
    monkeypatch.setattr(ist, "load_client", lambda slug: loaded)

    # AI classify (lazy-imported from the classifier module as classify_story)
    def _classify_story(*, story, loaded_client):
        if classify_raises:
            raise RuntimeError("gemini down")
        if classify_returns_none:
            return None  # no prompt configured -> clean skip
        return ClassifyResult(
            category="News", confidence=0.9, reasoning="r", provider="gemini"
        )
    monkeypatch.setattr(classifier_mod, "classify_story", _classify_story)

    # silence Telegram (RunContext fires notify_run_started/completed lazily)
    monkeypatch.setattr(telegram_mod, "notify_run_started", lambda *a, **k: None)
    monkeypatch.setattr(telegram_mod, "notify_run_completed", lambda *a, **k: None)
    monkeypatch.setattr(telegram_mod, "send", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)

    return rec


def test_ingest_new_and_existing_stories(monkeypatch):
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    rec = _patch_ingest_stories(
        monkeypatch,
        stories=[_story("100"), _story("200")],
        existing_ids={"200"},  # 200 already known -> skipped entirely
    )
    run_ids = ingest_stories_for_client("testclient")

    assert run_ids == ["run-1"]
    # Only the new story is inserted; the existing one is skipped (no metrics
    # path for stories — they're either new or known).
    assert len(rec["insert_story"]) == 1
    assert len(rec["download_and_record"]) == 1   # its single media row
    assert len(rec["update_story_ai"]) == 1       # classified the new story only
    # discovered pk differed from cached None -> persisted
    assert len(rec["set_account_platform_id"]) == 1
    assert rec["finish_run"][0][1]["status"] == "success"
    assert rec["finish_run"][0][1]["items_new"] == 1


def test_ingest_stories_isolates_classify_failure(monkeypatch):
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    rec = _patch_ingest_stories(
        monkeypatch, stories=[_story("100")], classify_raises=True
    )
    run_ids = ingest_stories_for_client("testclient")

    assert run_ids == ["run-1"]
    # Story + media are persisted before classify runs, so an AI failure must
    # not lose them.
    assert len(rec["insert_story"]) == 1
    assert len(rec["download_and_record"]) == 1
    assert len(rec["update_story_ai"]) == 0
    assert len(rec["increment_story_ai_attempts"]) == 1
    # The story still counted as new (it was inserted before classify) -> partial.
    assert rec["finish_run"][0][1]["status"] == "partial"


def test_ingest_stories_classify_none_is_clean_skip(monkeypatch):
    # classify_story returns None when no prompt is configured — a clean skip,
    # distinct from the raise path: no AI write, no retry, no error.
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    rec = _patch_ingest_stories(
        monkeypatch, stories=[_story("100")], classify_returns_none=True
    )
    run_ids = ingest_stories_for_client("testclient")

    assert run_ids == ["run-1"]
    assert len(rec["insert_story"]) == 1
    assert len(rec["update_story_ai"]) == 0
    assert len(rec["increment_story_ai_attempts"]) == 0
    assert rec["finish_run"][0][1]["status"] == "success"


def test_ingest_stories_isolates_media_403(monkeypatch):
    # A 403 on an expired signed URL (or any download failure) is isolated per
    # media: the story row still persists and the run records a download error.
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    rec = _patch_ingest_stories(
        monkeypatch, stories=[_story("100", media_count=2)], download_raises=True
    )
    run_ids = ingest_stories_for_client("testclient")

    assert run_ids == ["run-1"]
    assert len(rec["insert_story"]) == 1            # story row survives the 403
    # First media 403s, but the loop continues to the second -> both attempted.
    assert len(rec["download_and_record"]) == 2
    err_stages = [k.get("stage") for (_a, k) in rec["record_item_error"]]
    assert "download_media" in err_stages
    # The story was still inserted and classified -> it counts as new.
    assert rec["finish_run"][0][1]["items_new"] == 1


def test_ingest_stories_skips_media_without_source_url(monkeypatch):
    # Story media with no source_url is skipped with a download_media error,
    # never passed to the downloader.
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    rec = _patch_ingest_stories(
        monkeypatch, stories=[_story("100", with_source=False)]
    )
    ingest_stories_for_client("testclient")

    assert len(rec["insert_story"]) == 1
    assert len(rec["download_and_record"]) == 0     # never reached the downloader
    err_stages = [k.get("stage") for (_a, k) in rec["record_item_error"]]
    assert "download_media" in err_stages


def test_ingest_stories_instagram_only(monkeypatch):
    # Stories are Instagram-only; an active facebook account is skipped, not an
    # error (Facebook stories are Phase B).
    from social_bot.pipeline import ingest_stories as ist
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    _patch_ingest_stories(monkeypatch, stories=[_story("100")])
    fb = SimpleNamespace(platform="facebook", handle="fbonly", is_owned=True)
    loaded = SimpleNamespace(
        slug="testclient", name="Test Client", active_accounts=[fb],
        config=SimpleNamespace(accounts=[fb], ai=SimpleNamespace(prompt_version="v1")),
    )
    monkeypatch.setattr(ist, "load_client", lambda slug: loaded)

    run_ids = ingest_stories_for_client("testclient")
    assert run_ids == []  # facebook story account ignored, not an error


def test_ingest_stories_account_override_ignores_active_flag(monkeypatch):
    # client.yaml is authoritative: an explicit --account override scrapes that
    # handle even when it is not in active_accounts (DB is_active can be stale).
    from social_bot.pipeline import ingest_stories as ist
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    _patch_ingest_stories(monkeypatch, stories=[_story("100")])
    inactive = SimpleNamespace(platform="instagram", handle="paused", is_owned=True)
    loaded = SimpleNamespace(
        slug="testclient", name="Test Client",
        active_accounts=[],                 # not active per the DB-derived view
        config=SimpleNamespace(             # but present in client.yaml
            accounts=[inactive], ai=SimpleNamespace(prompt_version="v1")
        ),
    )
    monkeypatch.setattr(ist, "load_client", lambda slug: loaded)

    # No override -> nothing runs (follows active_accounts).
    assert ingest_stories_for_client("testclient") == []
    # Explicit override -> runs against the YAML account regardless of active.
    run_ids = ingest_stories_for_client("testclient", account_handle="paused")
    assert run_ids == ["run-1"]


# =====================================================================
# publish_report
# =====================================================================


def _patch_publish(monkeypatch, *, drive_raises=False):
    from social_bot.reports import renderer
    from social_bot.reports.renderer import _BuiltReport
    from social_bot.storage.reports import UploadedReport

    rec: dict[str, list] = {"upload": [], "drive": [], "notify": []}

    built = _BuiltReport(
        path=Path("/tmp/reports/testclient_April_2026.pptx"),
        report=SimpleNamespace(client_name="Test Client"),
        slide_count=14,
    )
    monkeypatch.setattr(renderer, "_build_report", lambda *a, **k: built)

    def _upload(client_slug, path):
        rec["upload"].append((client_slug, path))
        return UploadedReport(
            storage_path="testclient/x.pptx", signed_url="https://signed", bytes_size=999
        )
    monkeypatch.setattr(renderer, "upload_report", _upload)

    def _drive_upload(client_slug, path):
        rec["drive"].append((client_slug, path))
        if drive_raises:
            raise RuntimeError("drive 500")
        return {"id": "file-1", "webViewLink": "https://drive/view"}
    monkeypatch.setattr(renderer.drive, "upload_report", _drive_upload)

    monkeypatch.setattr(
        renderer.telegram, "notify_report_generated",
        lambda **kwargs: rec["notify"].append(kwargs),
    )
    return rec, built


def test_publish_report_full_fanout(monkeypatch):
    from social_bot.reports.renderer import publish_report

    rec, built = _patch_publish(monkeypatch)
    period = SimpleNamespace(label="April 2026")

    path, uploaded = publish_report("testclient", period)

    assert path == built.path
    assert uploaded.signed_url == "https://signed"
    assert len(rec["upload"]) == 1
    assert len(rec["drive"]) == 1
    assert len(rec["notify"]) == 1
    assert rec["notify"][0]["signed_url"] == "https://signed"
    assert rec["notify"][0]["slide_count"] == 14


def test_publish_report_survives_drive_failure(monkeypatch):
    # Drive is a best-effort sidecar — its failure must not break the Supabase
    # + Telegram delivery path that cron depends on.
    from social_bot.reports.renderer import publish_report

    rec, built = _patch_publish(monkeypatch, drive_raises=True)
    period = SimpleNamespace(label="April 2026")

    path, uploaded = publish_report("testclient", period)

    assert path == built.path
    assert len(rec["drive"]) == 1      # attempted
    assert len(rec["upload"]) == 1     # Supabase upload still happened
    assert len(rec["notify"]) == 1     # Telegram still fired
