"""
TikTok scraper (Apify-only tier) - fixture-driven contract tests.

Fixture dicts are trimmed copies of real actor captures:
  - clockworks/tiktok-profile-scraper (posts, with the video-download add-on)
  - igview-owner/tiktok-story-viewer (stories, incl. the no_stories sentinel)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from social_bot.config import Settings
from social_bot.scrapers.base import REEL_COVER_SLIDE_INDEX
from social_bot.scrapers.registry import get_scraper, supported_platforms
from social_bot.scrapers.tiktok import TikTokScraper

# =========================
# Fakes (ApifyClient stand-in)
# =========================


class _FakeActor:
    def __init__(self, client: _FakeApifyClient, name: str) -> None:
        self._client = client
        self._name = name

    def call(self, run_input: dict[str, Any]) -> dict[str, Any] | None:
        self._client.calls.append((self._name, run_input))
        return {"defaultDatasetId": "ds-1"}


class _FakeDataset:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def iterate_items(self) -> Any:
        return iter(self._items)


class _FakeApifyClient:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def actor(self, name: str) -> _FakeActor:
        return _FakeActor(self, name)

    def dataset(self, dataset_id: str) -> _FakeDataset:
        return _FakeDataset(self._items)


def _scraper(items: list[dict[str, Any]]) -> tuple[TikTokScraper, _FakeApifyClient]:
    """TikTokScraper without settings/ApifyClient side effects."""
    s = object.__new__(TikTokScraper)
    client = _FakeApifyClient(items)
    s._client = client  # type: ignore[assignment]
    s._actor = "clockworks/tiktok-profile-scraper"
    s._story_actor = "igview-owner/tiktok-story-viewer"
    s.discovered_platform_account_id = None
    return s, client


# =========================
# Fixture items (trimmed from real captures)
# =========================

_KV = "https://api.apify.com/v2/key-value-stores/puFxQwDjn8N8iBYOk/records"


def _video_item() -> dict[str, Any]:
    return {
        "id": "7660477545850227990",
        "text": "business as usual, no biggie #redbull #givesyouwiiings",
        "createTime": 1783612800,
        "createTimeISO": "2026-07-09T16:00:00.000Z",
        "authorMeta": {
            "id": "160822079959736320",
            "name": "redbull",
            "profileUrl": "https://www.tiktok.com/@redbull",
        },
        "webVideoUrl": "https://www.tiktok.com/@redbull/video/7660477545850227990",
        "videoMeta": {
            "height": 1024,
            "width": 576,
            "duration": 24,
            "coverUrl": f"{_KV}/cover-redbull-20260709160000-7660477545850227990.jpg",
            "definition": "540p",
            "format": "mp4",
            "downloadAddr": f"{_KV}/video-redbull-20260709160000-7660477545850227990.mp4",
        },
        "diggCount": 1829,
        "shareCount": 9,
        "playCount": 26300,
        "collectCount": 41,
        "commentCount": 73,
        "isSlideshow": False,
        "isPinned": False,
        "mediaUrls": [f"{_KV}/video-redbull-20260709160000-7660477545850227990.mp4"],
        "input": "redbull",
    }


def _slideshow_item() -> dict[str, Any]:
    return {
        "id": "7553949029885955350",
        "text": "photo dump from the weekend",
        "createTime": 1758790819,
        "createTimeISO": "2025-09-25T09:00:19.000Z",
        "authorMeta": {"id": "160822079959736320", "name": "redbull"},
        "webVideoUrl": "https://www.tiktok.com/@redbull/video/7553949029885955350",
        "diggCount": 739700,
        "shareCount": 52700,
        "playCount": 9400000,
        "collectCount": 37228,
        "commentCount": 3962,
        "isSlideshow": True,
        "isPinned": False,
        "mediaUrls": [
            f"{_KV}/slide-redbull-0.jpg",
            f"{_KV}/slide-redbull-1.jpg",
            f"{_KV}/slide-redbull-2.jpg",
        ],
        "input": "redbull",
    }


def _story_item() -> dict[str, Any]:
    return {
        "source": "tiktok",
        "aweme_id": "v15044gf0000d97t91nog65pvbdfm0fg",
        "video_id": "7660575283753258270",
        "unique_id": "espn",
        "region": "US",
        "title": "",
        "cover_url": "https://p16-common-sign.tiktokcdn-us.com/story-cover.jpeg",
        "video_url": "https://v16m.tiktokcdn-us.com/story-video.mp4",
        "duration": 10,
        "create_time": 1783616685,
        "create_time_date": "2026-07-09T17:04:45.000Z",
        "is_ad": False,
        "author_info": {
            "id": "6663294979903422470",
            "unique_id": "espn",
            "nickname": "ESPN",
        },
    }


def _sentinel_item(handle: str) -> dict[str, Any]:
    return {
        "source": "tiktok",
        "unique_id": handle,
        "message": "No stories available",
        "status": "no_stories",
        "checked_at": "2026-07-09T21:24:16.686Z",
    }


# =========================
# Posts
# =========================


def test_video_post_normalized_fully() -> None:
    raw = _video_item()
    s, _ = _scraper([raw])
    posts = s.scrape_posts("redbull")

    assert len(posts) == 1
    post = posts[0]
    assert post.platform == "tiktok"
    assert post.platform_post_id == "7660477545850227990"
    assert post.post_type == "video"
    assert post.caption == "business as usual, no biggie #redbull #givesyouwiiings"
    assert post.permalink == "https://www.tiktok.com/@redbull/video/7660477545850227990"
    assert post.posted_at == datetime(2026, 7, 9, 16, 0, 0, tzinfo=UTC)
    # Metrics mapping: view AND play both come from playCount.
    assert post.like_count == 1829
    assert post.comment_count == 73
    assert post.view_count == 26300
    assert post.play_count == 26300
    assert post.save_count == 41
    assert post.share_count == 9
    # KV mp4 at slide 0 + cover at the sentinel index.
    assert len(post.media) == 2
    video = post.media[0]
    assert video.slide_index == 0
    assert video.media_type == "video"
    assert video.source_url.endswith(".mp4")
    assert video.duration_seconds == 24
    assert video.width == 576
    assert video.height == 1024
    cover = post.media[1]
    assert cover.slide_index == REEL_COVER_SLIDE_INDEX
    assert cover.media_type == "image"
    assert cover.source_url.endswith(".jpg")
    # Full raw item preserved for re-derivation.
    assert post.raw is raw


def test_slideshow_is_carousel_with_image_per_url() -> None:
    s, _ = _scraper([_slideshow_item()])
    posts = s.scrape_posts("redbull")

    assert len(posts) == 1
    post = posts[0]
    assert post.post_type == "carousel"
    assert len(post.media) == 3
    for i, m in enumerate(post.media):
        assert m.slide_index == i
        assert m.media_type == "image"
        assert m.source_url.endswith(f"slide-redbull-{i}.jpg")
    # No reel-cover sentinel on slideshows.
    assert all(m.slide_index != REEL_COVER_SLIDE_INDEX for m in post.media)


def _real_slideshow_item() -> dict[str, Any]:
    """Real 2026-07-13 clockworks capture shape: slideshow with the download
    add-on returns empty mediaUrls and carries images in slideshowImageLinks
    ({tiktokLink: short-lived CDN URL, downloadLink: durable Apify KV copy})."""
    raw = _slideshow_item()
    raw["mediaUrls"] = []
    raw["slideshowImageLinks"] = [
        {
            "tiktokLink": "https://p16-sign.tiktokcdn-us.com/obj/slide-0.jpeg?x-expires=1",
            "downloadLink": f"{_KV}/slideshow-image-redbull-20250925090019-7553949029885955350-0.jpg",
        },
        {
            "tiktokLink": "https://p16-sign.tiktokcdn-us.com/obj/slide-1.jpeg?x-expires=1",
            "downloadLink": f"{_KV}/slideshow-image-redbull-20250925090019-7553949029885955350-1.jpg",
        },
    ]
    return raw


def test_slideshow_real_shape_uses_slideshow_image_links_download_link() -> None:
    # Bug repro (root-caused 2026-07-13): real actor slideshow items have
    # mediaUrls == [] and images in slideshowImageLinks; current code returns
    # zero media and the post persists forever with no images.
    raw = _real_slideshow_item()
    s, _ = _scraper([raw])
    posts = s.scrape_posts("redbull")

    assert len(posts) == 1
    post = posts[0]
    assert post.post_type == "carousel"
    assert len(post.media) == 2
    for i, m in enumerate(post.media):
        assert m.slide_index == i
        assert m.media_type == "image"
        # Must be the durable Apify KV downloadLink, not the short-lived CDN URL.
        assert m.source_url == raw["slideshowImageLinks"][i]["downloadLink"]
    assert all(m.slide_index != REEL_COVER_SLIDE_INDEX for m in post.media)


def test_slideshow_image_link_without_download_link_falls_back_to_tiktok_link() -> None:
    raw = _real_slideshow_item()
    del raw["slideshowImageLinks"][1]["downloadLink"]
    s, _ = _scraper([raw])
    posts = s.scrape_posts("redbull")

    assert len(posts) == 1
    media = posts[0].media
    assert len(media) == 2
    assert media[0].source_url == raw["slideshowImageLinks"][0]["downloadLink"]
    assert media[1].source_url == raw["slideshowImageLinks"][1]["tiktokLink"]


def test_video_without_media_urls_falls_back_to_download_addr() -> None:
    raw = _video_item()
    raw["mediaUrls"] = []
    s, _ = _scraper([raw])
    posts = s.scrape_posts("redbull")

    assert len(posts) == 1
    video = posts[0].media[0]
    assert video.media_type == "video"
    assert video.source_url == raw["videoMeta"]["downloadAddr"]


def test_video_without_any_video_url_emits_cover_only() -> None:
    raw = _video_item()
    raw["mediaUrls"] = []
    del raw["videoMeta"]["downloadAddr"]
    s, _ = _scraper([raw])
    posts = s.scrape_posts("redbull")

    assert len(posts) == 1
    media = posts[0].media
    assert len(media) == 1
    assert media[0].media_type == "image"
    assert media[0].slide_index == REEL_COVER_SLIDE_INDEX


def test_missing_id_skips_item_but_batch_survives() -> None:
    bad = _video_item()
    bad["id"] = ""
    s, _ = _scraper([bad, _slideshow_item()])
    posts = s.scrape_posts("redbull")

    assert [p.platform_post_id for p in posts] == ["7553949029885955350"]


def test_degraded_item_emits_post_with_none_metrics() -> None:
    degraded = _video_item()
    for key in ("diggCount", "commentCount", "playCount", "shareCount", "collectCount"):
        del degraded[key]
    s, _ = _scraper([degraded, _slideshow_item()])
    posts = s.scrape_posts("redbull")

    assert len(posts) == 2
    post = posts[0]
    assert post.platform_post_id == "7660477545850227990"
    assert post.like_count is None
    assert post.comment_count is None
    assert post.view_count is None
    assert post.play_count is None
    assert post.share_count is None


def test_empty_dataset_returns_empty_list() -> None:
    s, _ = _scraper([])
    assert s.scrape_posts("redbull") == []


def test_discovered_platform_account_id_from_author_meta() -> None:
    s, _ = _scraper([_video_item()])
    s.scrape_posts("redbull")
    assert s.discovered_platform_account_id == "160822079959736320"


def test_actor_input_defaults_without_dates() -> None:
    s, client = _scraper([])
    s.scrape_posts("@redbull", limit=15)

    assert len(client.calls) == 1
    actor, run_input = client.calls[0]
    assert actor == "clockworks/tiktok-profile-scraper"
    assert run_input == {
        "profiles": ["redbull"],
        "resultsPerPage": 15,
        "shouldDownloadVideos": True,
        "shouldDownloadCovers": True,
        "shouldDownloadSlideshowImages": True,
        "excludePinnedPosts": False,
    }


def test_actor_input_includes_date_filters_when_given() -> None:
    s, client = _scraper([])
    s.scrape_posts("redbull", since="2026-06-01", until="2026-07-01")

    _, run_input = client.calls[0]
    assert run_input["oldestPostDateUnified"] == "2026-06-01"
    assert run_input["newestPostDate"] == "2026-07-01"
    assert run_input["resultsPerPage"] == 30  # limit default


# =========================
# Stories
# =========================


def test_story_normalized_from_espn_shape() -> None:
    raw = _story_item()
    s, client = _scraper([raw])
    stories = s.scrape_stories("@espn")

    assert client.calls == [
        ("igview-owner/tiktok-story-viewer", {"uniqueIds": ["espn"]})
    ]
    assert len(stories) == 1
    story = stories[0]
    assert story.platform == "tiktok"
    assert story.platform_story_id == "7660575283753258270"
    assert story.posted_at == datetime.fromtimestamp(1783616685, tz=UTC)
    assert story.expires_at == story.posted_at + timedelta(hours=24)
    assert story.caption is None  # empty title -> None
    assert len(story.media) == 1
    media = story.media[0]
    assert media.slide_index == 0
    assert media.media_type == "video"
    assert media.source_url == raw["video_url"]
    assert media.duration_seconds == 10
    assert story.raw is raw
    # author_info carries the stable numeric user id.
    assert s.discovered_platform_account_id == "6663294979903422470"


def test_no_stories_sentinel_filtered_to_empty() -> None:
    s, _ = _scraper([_sentinel_item("duolingo")])
    assert s.scrape_stories("duolingo") == []


def test_mixed_sentinels_and_real_story_yield_one_story() -> None:
    s, _ = _scraper([_sentinel_item("duolingo"), _story_item(), _sentinel_item("nba")])
    stories = s.scrape_stories("espn")
    assert [st.platform_story_id for st in stories] == ["7660575283753258270"]


def test_story_with_cover_but_no_video_is_image() -> None:
    raw = _story_item()
    del raw["video_url"]
    s, _ = _scraper([raw])
    stories = s.scrape_stories("espn")

    assert len(stories) == 1
    media = stories[0].media[0]
    assert media.media_type == "image"
    assert media.source_url == raw["cover_url"]


# =========================
# Registry + settings
# =========================


def test_registry_returns_tiktok_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = SimpleNamespace(
        apify_token="test-token",
        apify_tiktok_actor="clockworks/tiktok-profile-scraper",
        apify_tiktok_story_actor="igview-owner/tiktok-story-viewer",
    )
    monkeypatch.setattr(
        "social_bot.scrapers.tiktok.get_settings", lambda: fake_settings
    )
    scraper = get_scraper("tiktok")
    assert isinstance(scraper, TikTokScraper)
    assert scraper.platform == "tiktok"
    assert "tiktok" in supported_platforms()


def test_settings_have_tiktok_actor_defaults() -> None:
    settings = Settings(
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SERVICE_KEY="test-key",
        APIFY_TOKEN="test-token",
        _env_file=None,
    )
    assert settings.apify_tiktok_actor == "clockworks/tiktok-profile-scraper"
    assert settings.apify_tiktok_story_actor == "igview-owner/tiktok-story-viewer"


def test_story_with_status_field_and_id_is_kept() -> None:
    # Regression pin: the sentinel filter keys on id-absence, NOT on the mere
    # presence of a status field. If the actor starts stamping status="ok" on
    # real items, stories must not silently vanish.
    raw = _story_item()
    raw["status"] = "ok"
    s, _ = _scraper([raw])
    stories = s.scrape_stories("espn")
    assert [st.platform_story_id for st in stories] == ["7660575283753258270"]


def test_millisecond_epoch_create_time_yields_none_posted_at_not_a_drop() -> None:
    # A 13-digit ms epoch is out of range for fromtimestamp; the guarded
    # parser returns None and the post is still emitted.
    raw = _video_item()
    raw.pop("createTimeISO", None)
    raw["createTime"] = 1783616685000  # milliseconds
    s, _ = _scraper([raw])
    posts = s.scrape_posts("redbull")
    assert len(posts) == 1
    assert posts[0].posted_at is None
