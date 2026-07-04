"""
Tests for the retry_ai CLI job.

Everything external is faked at its module boundary: queries, load_client,
classify, Telegram, and the storage download. The key contract under test:
retry runs happen hours after the original scrape, when the scraped CDN
source_url has expired, so media bytes MUST come from Supabase Storage
(storage_path via storage.media.download_from_storage), never from source_url.
That is exactly how describe_posts._fetch_blobs already works.
"""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

from social_bot.ai.providers.gemini import ClassifyResult
from social_bot.db import queries

STORAGE_PATH = "testclient/testhandle/instagram/2026/04/post-1_0.jpg"


def _patch_retry(monkeypatch):
    """Fake the retry_ai external surface. Returns a call recorder."""
    import social_bot.storage.media as storage_media
    from scripts import retry_ai

    rec: dict[str, list] = defaultdict(list)

    def _record(name, ret=None):
        def fn(*args, **kwargs):
            rec[name].append((args, kwargs))
            return ret
        return fn

    monkeypatch.setattr(
        queries, "find_posts_needing_ai",
        _record("find_posts_needing_ai", [
            {
                "id": "post-1",
                "platform": "instagram",
                "platform_post_id": "pp-1",
                "post_type": "image",
                "caption": "a caption",
                "permalink": "https://instagram.com/p/pp-1/",
                "posted_at": None,
                "account_id": "acct-1",
            }
        ]),
    )
    monkeypatch.setattr(
        queries, "list_media_for_post",
        _record("list_media_for_post", [
            {
                "id": "media-1",
                "slide_index": 0,
                "media_type": "image",
                "source_url": "https://cdn.expired/old.jpg",  # long dead by retry time
                "storage_path": STORAGE_PATH,                 # permanent copy
            }
        ]),
    )
    monkeypatch.setattr(
        queries, "get_account_with_client",
        _record("get_account_with_client", {
            "id": "acct-1",
            "platform": "instagram",
            "handle": "testhandle",
            "client_slug": "testclient",
        }),
    )
    monkeypatch.setattr(queries, "update_post_ai", _record("update_post_ai"))
    monkeypatch.setattr(
        queries, "increment_post_ai_attempts", _record("increment_post_ai_attempts", 1)
    )

    loaded = SimpleNamespace(
        slug="testclient",
        name="Test Client",
        config=SimpleNamespace(ai=SimpleNamespace(prompt_version="v1")),
    )
    monkeypatch.setattr(retry_ai, "load_client", lambda slug: loaded)

    def _classify(*, post, loaded_client, blobs=None):
        rec["classify"].append(
            ((), {"post": post, "loaded_client": loaded_client, "blobs": blobs})
        )
        return ClassifyResult(category="News", confidence=0.9, reasoning="r")
    monkeypatch.setattr(retry_ai, "classify", _classify)

    # storage download boundary — record which storage_path was fetched.
    def _download(storage_path):
        rec["download_from_storage"].append(storage_path)
        return b"image-bytes", "image/jpeg"
    # Patch the source module AND (raising=False) any name the fixed retry_ai
    # binds at import time, so the recorder is hit regardless of import style.
    monkeypatch.setattr(storage_media, "download_from_storage", _download)
    monkeypatch.setattr(retry_ai, "download_from_storage", _download, raising=False)

    # silence notifications, logging setup, and the inter-post delay
    monkeypatch.setattr(retry_ai, "notify_ai_retry_completed", _record("notify_completed"))
    monkeypatch.setattr(retry_ai, "notify_ai_exhausted", _record("notify_exhausted"))
    monkeypatch.setattr(retry_ai, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)

    return rec


# RED: bug 4 — passes once retry_ai fetches media bytes from storage_path via
# download_from_storage instead of rebuilding ScrapedMedia from the expired
# CDN source_url.
def test_retry_ai_uses_storage_path_not_expired_source_url(monkeypatch):
    from scripts.retry_ai import main

    rec = _patch_retry(monkeypatch)
    main(run_id="run-orig")

    # The post was retried and classified.
    assert len(rec["classify"]) == 1
    assert len(rec["update_post_ai"]) == 1
    # Media bytes must come from the permanent storage copy: the CDN URL in
    # media.source_url is expired by the time the retry cron fires.
    assert rec["download_from_storage"] == [STORAGE_PATH]
    # And those storage bytes are what classification actually receives.
    blobs = rec["classify"][0][1]["blobs"]
    assert blobs and blobs[0].bytes_data == b"image-bytes"
