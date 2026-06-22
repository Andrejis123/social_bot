"""
Tests for the HikerAPI post normalizer.

Fixtures are real responses captured against agapeslovensko, pulzeczech, and
iluminatecz on 2026-05-24. They cover all three IG media_type values:
  1 = image (pulzeczech feed post)
  2 = video/reel (agape + pulzeczech + iluminatecz)
  8 = carousel (pulzeczech 3-child, iluminatecz 6-child)

Synthetic payloads cover edge cases (missing fields, video_url fallback).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from social_bot.scrapers.base import REEL_COVER_SLIDE_INDEX
from social_bot.scrapers.instagram import _normalize_post_hiker

FIXTURES = Path(__file__).parent / "fixtures"


def _load_items(fixture_name: str) -> list[dict]:
    data = json.loads((FIXTURES / fixture_name).read_text())
    return data["response"]["items"]


def _find_by_code(items: list[dict], code: str) -> dict:
    for it in items:
        if it.get("code") == code:
            return it
    raise KeyError(f"no item with code={code!r}")


# -------------------------
# Real-fixture coverage — one per media_type
# -------------------------


def test_reel_from_agapeslovensko():
    item = _find_by_code(_load_items("hiker_medias_agape.json"), "DWjOrfjk1gc")
    post = _normalize_post_hiker(item)

    assert post.platform == "instagram"
    assert post.platform_post_id == "3864997466685528092"
    assert post.permalink == "https://www.instagram.com/p/DWjOrfjk1gc/"
    assert post.post_type == "reel"
    assert post.permalink == "https://www.instagram.com/p/DWjOrfjk1gc/"
    assert post.like_count == 352
    assert post.comment_count == 8
    assert post.caption is not None and "Bod zlomu" in post.caption

    # A reel yields two media rows: the video at slide 0, plus its cover image
    # stored at the sentinel index at scrape time (so reports don't chase stale
    # IG URLs later). Regression guard for the scrape-time cover-storage feature.
    assert len(post.media) == 2
    m = post.media[0]
    assert m.slide_index == 0
    assert m.media_type == "video"
    assert m.source_url.startswith("https://")
    assert ".mp4" in m.source_url  # CDN URLs have query params after the extension
    assert m.duration_seconds is not None and m.duration_seconds > 0

    cover = post.media[1]
    assert cover.slide_index == REEL_COVER_SLIDE_INDEX
    assert cover.media_type == "image"
    assert cover.source_url.startswith("https://")


def test_single_image_from_pulzeczech():
    item = _find_by_code(_load_items("hiker_medias_pulzeczech.json"), "DYhI0vbDAnn")
    post = _normalize_post_hiker(item)

    assert post.platform_post_id == "3900437560984078823"
    assert post.post_type == "image"
    assert post.like_count == 15
    assert post.comment_count == 2

    assert len(post.media) == 1
    m = post.media[0]
    assert m.media_type == "image"
    assert m.source_url.startswith("https://")


def test_carousel_3_children_from_pulzeczech():
    item = _find_by_code(_load_items("hiker_medias_pulzeczech.json"), "DVtiZx5jR7u")
    post = _normalize_post_hiker(item)

    assert post.platform_post_id == "3849884561618837230"
    assert post.post_type == "carousel"

    assert len(post.media) == 3
    assert [m.slide_index for m in post.media] == [0, 1, 2]
    for m in post.media:
        assert m.media_type == "image"
        assert m.source_url.startswith("https://")


def test_carousel_6_children_from_iluminatecz():
    item = _find_by_code(_load_items("hiker_medias_iluminatecz.json"), "DYh8ZVnDTpZ")
    post = _normalize_post_hiker(item)

    assert post.post_type == "carousel"
    assert len(post.media) == 6
    assert [m.slide_index for m in post.media] == [0, 1, 2, 3, 4, 5]


def test_caption_extracted_from_nested_object():
    # HikerAPI's /v2 endpoint always nests caption under {text: ...}.
    # Regression guard: must not look at top-level `caption_text` (it's None).
    item = _find_by_code(_load_items("hiker_medias_pulzeczech.json"), "DYo3bA8j6Yt")
    post = _normalize_post_hiker(item)
    assert post.caption is not None
    assert len(post.caption) > 10


def test_taken_at_is_parsed_from_epoch():
    item = _find_by_code(_load_items("hiker_medias_pulzeczech.json"), "DYo3bA8j6Yt")
    post = _normalize_post_hiker(item)
    assert post.posted_at is not None
    assert post.posted_at.year == 2026


# -------------------------
# Synthetic edge cases
# -------------------------


def test_missing_pk_raises():
    raw = {"code": "ABC", "media_type": 1, "image_versions2": {"candidates": [{"url": "x"}]}}
    with pytest.raises(ValueError, match="no pk"):
        _normalize_post_hiker(raw)


def test_missing_code_raises():
    raw = {"pk": "123", "media_type": 1, "image_versions2": {"candidates": [{"url": "x"}]}}
    with pytest.raises(ValueError, match="no code"):
        _normalize_post_hiker(raw)


def test_video_url_fallback_when_no_video_versions():
    # If video_versions is missing or empty, fall through to top-level video_url.
    raw = {
        "code": "ABC123",
        "pk": "1000000000000000001",
        "media_type": 2,
        "product_type": "feed",  # video, not reel
        "video_url": "https://cdn.example/fallback.mp4",
        "video_duration": 5.0,
        "caption": {"text": "hi"},
        "taken_at": 1700000000,
        "like_count": 1,
        "comment_count": 0,
    }
    post = _normalize_post_hiker(raw)
    assert post.post_type == "video"
    assert post.media[0].source_url == "https://cdn.example/fallback.mp4"
    assert post.media[0].duration_seconds == 5.0
    assert post.caption == "hi"


def test_thumbnail_url_fallback_for_image_without_versions():
    raw = {
        "code": "IMG1",
        "pk": "1000000000000000002",
        "media_type": 1,
        "product_type": "feed",
        "thumbnail_url": "https://cdn.example/thumb.jpg",
        "caption": None,  # no caption set
        "taken_at": 1700000000,
    }
    post = _normalize_post_hiker(raw)
    assert post.media[0].source_url == "https://cdn.example/thumb.jpg"
    assert post.caption is None


def test_carousel_with_empty_children_falls_back_to_cover():
    # Edge case: media_type=8 but carousel_media is empty.
    raw = {
        "code": "EMPTY_CAROUSEL",
        "pk": "1000000000000000003",
        "media_type": 8,
        "product_type": "carousel_container",
        "carousel_media": [],
        "image_versions2": {"candidates": [{"url": "https://cdn.example/cover.jpg"}]},
        "caption": {"text": "fallback"},
        "taken_at": 1700000000,
    }
    post = _normalize_post_hiker(raw)
    assert post.post_type == "carousel"
    assert len(post.media) == 1
    assert post.media[0].source_url == "https://cdn.example/cover.jpg"


def test_view_count_falls_back_to_play_count():
    raw = {
        "code": "VIEW1",
        "pk": "1000000000000000004",
        "media_type": 2,
        "product_type": "clips",
        "video_url": "https://cdn.example/v.mp4",
        "video_duration": 10.0,
        "view_count": 0,
        "play_count": 1500,
        "caption": {"text": "x"},
        "taken_at": 1700000000,
    }
    post = _normalize_post_hiker(raw)
    # view_count is 0 (falsy), so should fall through to play_count
    assert post.view_count == 1500
    assert post.play_count == 1500
