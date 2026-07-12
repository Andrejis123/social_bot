"""
Per-account isolation and --account targeting for the ingest pipelines.

A client config lists several accounts; the cron runs one pipeline invocation
per client. Two contracts locked here:

* Isolation: a scraper blow-up on account 1 (Apify outage, HikerAPI fatal,
  bad handle) must not abort accounts 2..N of the same run.
* Targeting: --account with a handle that exists on more than one platform
  and no --platform is ambiguous and must fail loudly instead of silently
  scraping both platforms (the prod cron passes handle only; scraping the
  dropped facebook twin caused a failure loop).

External surface faked exactly like tests/test_pipeline_e2e.py.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from social_bot.ai.providers.gemini import ClassifyResult
from social_bot.scrapers.base import ScrapedMedia, ScrapedPost, ScrapedStory


def _post(pid: str) -> ScrapedPost:
    return ScrapedPost(
        platform="instagram",
        platform_post_id=pid,
        post_type="image",
        caption="a caption",
        permalink=f"https://instagram.com/p/{pid}/",
        posted_at=datetime(2026, 4, 1, tzinfo=UTC),
        media=[ScrapedMedia(slide_index=0, media_type="image", source_url=f"https://cdn/{pid}.jpg")],
        like_count=5,
        comment_count=1,
        raw={"id": pid},
    )


def _story(sid: str) -> ScrapedStory:
    return ScrapedStory(
        platform="instagram",
        platform_story_id=sid,
        posted_at=datetime(2026, 4, 1, tzinfo=UTC),
        expires_at=datetime(2026, 4, 2, tzinfo=UTC),
        caption="a story caption",
        media=[ScrapedMedia(slide_index=0, media_type="image", source_url=f"https://cdn/{sid}.jpg")],
        raw={"id": sid},
    )


class _PerHandleScraper:
    """Raises for handles in `failing`; returns items for everyone else."""

    discovered_platform_account_id = None

    def __init__(self, items, failing: set[str]):
        self._items = items
        self._failing = failing

    def _serve(self, handle):
        if handle in self._failing:
            raise RuntimeError(f"scraper exploded for {handle}")
        return self._items

    def scrape_posts(self, handle, **kwargs):
        return self._serve(handle)

    def scrape_stories(self, handle, **kwargs):
        return self._serve(handle)


def _base_patches(monkeypatch, rec):
    """Common db.queries + telegram fakes shared by posts and stories tests."""
    import social_bot.notifications.telegram as telegram_mod
    from social_bot.db import queries

    def _record(name, ret=None):
        def fn(*args, **kwargs):
            rec[name].append((args, kwargs))
            return ret
        return fn

    runs = {"n": 0}

    def _start_run(**kwargs):
        runs["n"] += 1
        rec["start_run"].append(((), kwargs))
        return f"run-{runs['n']}"

    monkeypatch.setattr(queries, "start_run", _start_run)
    monkeypatch.setattr(queries, "finish_run", _record("finish_run"))
    monkeypatch.setattr(queries, "record_item_error", _record("record_item_error"))
    monkeypatch.setattr(queries, "upsert_client", _record("upsert_client", "client-1"))

    def _upsert_account(**kwargs):
        rec["upsert_account"].append(((), kwargs))
        return {"id": f"acct-{kwargs['handle']}", "platform_account_id": "pk-cached"}

    monkeypatch.setattr(queries, "upsert_account", _upsert_account)
    monkeypatch.setattr(queries, "set_account_platform_id", _record("set_account_platform_id"))

    # posts surface
    monkeypatch.setattr(queries, "find_post", lambda platform, pid: None)
    monkeypatch.setattr(queries, "insert_post", _record("insert_post", "post-1"))
    monkeypatch.setattr(queries, "insert_media", _record("insert_media"))
    monkeypatch.setattr(queries, "append_post_metrics", _record("append_post_metrics"))
    monkeypatch.setattr(queries, "update_post_ai", _record("update_post_ai"))
    monkeypatch.setattr(queries, "increment_post_ai_attempts", _record("increment_post_ai_attempts"))

    # stories surface
    monkeypatch.setattr(queries, "find_story", lambda platform, sid: None)
    monkeypatch.setattr(queries, "insert_story", _record("insert_story", "story-1"))
    monkeypatch.setattr(queries, "update_story_ai", _record("update_story_ai"))
    monkeypatch.setattr(queries, "increment_story_ai_attempts", _record("increment_story_ai_attempts"))

    monkeypatch.setattr(telegram_mod, "notify_run_started", lambda *a, **k: None)
    monkeypatch.setattr(telegram_mod, "notify_run_completed", lambda *a, **k: None)
    monkeypatch.setattr(telegram_mod, "send", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)


def _loaded(accounts):
    return SimpleNamespace(
        slug="testclient",
        name="Test Client",
        active_accounts=list(accounts),
        config=SimpleNamespace(accounts=list(accounts), ai=SimpleNamespace(prompt_version="v1")),
    )


def _patch_posts(monkeypatch, *, accounts, failing=frozenset()):
    import social_bot.ai.classifier as classifier_mod
    from social_bot.pipeline import ingest_posts as ip

    rec: dict[str, list] = defaultdict(list)
    _base_patches(monkeypatch, rec)
    monkeypatch.setattr(
        ip, "download_and_upload",
        lambda **kwargs: SimpleNamespace(storage_path="bucket/path.jpg", bytes_size=42),
    )
    monkeypatch.setattr(
        ip, "get_scraper",
        lambda platform: _PerHandleScraper([_post("100")], set(failing)),
    )
    monkeypatch.setattr(ip, "load_client", lambda slug: _loaded(accounts))
    monkeypatch.setattr(
        classifier_mod, "classify",
        lambda **kwargs: ClassifyResult(category="News", confidence=0.9, reasoning="r"),
    )
    return rec


def _patch_stories(monkeypatch, *, accounts, failing=frozenset()):
    import social_bot.ai.classifier as classifier_mod
    from social_bot.pipeline import ingest_stories as ist

    rec: dict[str, list] = defaultdict(list)
    _base_patches(monkeypatch, rec)
    monkeypatch.setattr(
        ist, "_download_and_record",
        lambda **kwargs: rec["download_and_record"].append(((), kwargs)),
    )
    monkeypatch.setattr(
        ist, "get_scraper",
        lambda platform: _PerHandleScraper([_story("100")], set(failing)),
    )
    monkeypatch.setattr(ist, "load_client", lambda slug: _loaded(accounts))
    monkeypatch.setattr(
        classifier_mod, "classify_story",
        lambda **kwargs: ClassifyResult(category="News", confidence=0.9, reasoning="r"),
    )
    return rec


# =====================================================================
# Bug 5 — one account's scraper failure must not abort the others
# =====================================================================


# RED: bug 5 — passes once ingest_posts_for_client isolates a per-account
# scraper exception and continues with the remaining accounts.
def test_ingest_posts_second_account_survives_first_account_failure(monkeypatch):
    from social_bot.pipeline.ingest_posts import ingest_posts_for_client

    first = SimpleNamespace(platform="instagram", handle="broken", is_owned=True)
    second = SimpleNamespace(platform="instagram", handle="healthy", is_owned=True)
    rec = _patch_posts(monkeypatch, accounts=[first, second], failing={"broken"})

    run_ids = ingest_posts_for_client("testclient")

    # Both accounts got a run row; the second one actually ingested its post.
    handles = [k["handle"] for (_a, k) in rec["upsert_account"]]
    assert handles == ["broken", "healthy"]
    assert len(rec["insert_post"]) == 1
    assert len(run_ids) == 2
    # First run finished failed, second finished clean.
    statuses = [k["status"] for (_a, k) in rec["finish_run"]]
    assert statuses == ["failed", "success"]


# RED: bug 5 — passes once ingest_stories_for_client isolates a per-account
# scraper exception and continues with the remaining accounts.
def test_ingest_stories_second_account_survives_first_account_failure(monkeypatch):
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    first = SimpleNamespace(platform="instagram", handle="broken", is_owned=True)
    second = SimpleNamespace(platform="instagram", handle="healthy", is_owned=True)
    rec = _patch_stories(monkeypatch, accounts=[first, second], failing={"broken"})

    run_ids = ingest_stories_for_client("testclient")

    handles = [k["handle"] for (_a, k) in rec["upsert_account"]]
    assert handles == ["broken", "healthy"]
    assert len(rec["insert_story"]) == 1
    assert len(run_ids) == 2
    statuses = [k["status"] for (_a, k) in rec["finish_run"]]
    assert statuses == ["failed", "success"]


# =====================================================================
# Bug 9 — --account with a multi-platform handle and no --platform
# =====================================================================


# RED: bug 9 — passes once an ambiguous --account (handle present on more
# than one platform) without --platform raises a clear error instead of
# silently scraping both platforms. Contract choice: raising beats picking
# one platform because no default is safe (the cron caller must be fixed to
# pass --platform explicitly; a silent pick would mask config mistakes).
def test_ambiguous_account_handle_without_platform_raises(monkeypatch):
    from social_bot.pipeline.ingest_posts import ingest_posts_for_client

    ig = SimpleNamespace(platform="instagram", handle="dup", is_owned=True)
    fb = SimpleNamespace(platform="facebook", handle="dup", is_owned=True)
    rec = _patch_posts(monkeypatch, accounts=[ig, fb])

    with pytest.raises(ValueError, match="dup"):
        ingest_posts_for_client("testclient", account_handle="dup")
    # Nothing must have been scraped for either platform.
    assert len(rec["start_run"]) == 0


def test_stories_ambiguous_account_handle_raises(monkeypatch):
    # Mirror of the posts guard: with the stories gate covering more than one
    # platform (instagram + tiktok), --account on a dual-platform handle must
    # fail loudly instead of silently running both scrapers.
    from social_bot.pipeline.ingest_stories import ingest_stories_for_client

    ig = SimpleNamespace(platform="instagram", handle="dup", is_owned=True)
    tt = SimpleNamespace(platform="tiktok", handle="dup", is_owned=True)
    rec = _patch_stories(monkeypatch, accounts=[ig, tt])

    with pytest.raises(ValueError, match="dup"):
        ingest_stories_for_client("testclient", account_handle="dup")
    assert len(rec["start_run"]) == 0

    # Disambiguated by platform= it runs exactly one account.
    ingest_stories_for_client("testclient", account_handle="dup", platform="tiktok")
    assert len(rec["start_run"]) == 1
