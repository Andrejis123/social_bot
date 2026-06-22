"""
Pure-function tests for the Instagram normalizer.

No network, no Supabase, no Apify — just feeds synthetic payloads through the
shape detection + field mapping logic. If Apify changes its output schema,
update the fixtures here first and the normalizer follows.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from social_bot.scrapers.base import REEL_COVER_SLIDE_INDEX
from social_bot.scrapers.instagram import _normalize_post, _normalize_post_fallback


def test_normalizes_single_image():
    raw = {
        "id": "123",
        "shortCode": "ABC",
        "type": "Image",
        "caption": "hello",
        "url": "https://instagram.com/p/ABC/",
        "timestamp": "2026-04-01T12:00:00.000Z",
        "displayUrl": "https://cdn.instagram.com/image.jpg",
        "likesCount": 10,
        "commentsCount": 2,
    }
    post = _normalize_post(raw)

    assert post.platform == "instagram"
    assert post.platform_post_id == "123"
    assert post.post_type == "image"
    assert post.caption == "hello"
    assert post.like_count == 10
    assert len(post.media) == 1
    assert post.media[0].slide_index == 0
    assert post.media[0].media_type == "image"
    assert post.media[0].source_url == "https://cdn.instagram.com/image.jpg"


def test_normalizes_carousel_with_mixed_children():
    raw = {
        "id": "abc",
        "shortCode": "XYZ",
        "type": "Sidecar",
        "caption": "carousel test",
        "timestamp": "2026-04-01T00:00:00.000Z",
        "childPosts": [
            {"type": "Image", "displayUrl": "https://cdn/1.jpg"},
            {"type": "Video", "videoUrl": "https://cdn/2.mp4", "videoDuration": 12.3},
            {"type": "Image", "displayUrl": "https://cdn/3.jpg"},
        ],
    }
    post = _normalize_post(raw)

    assert post.post_type == "carousel"
    assert [m.media_type for m in post.media] == ["image", "video", "image"]
    assert [m.slide_index for m in post.media] == [0, 1, 2]
    assert post.media[1].duration_seconds == 12.3


def test_reel_detected_via_product_type():
    raw = {
        "id": "r1",
        "type": "Video",
        "productType": "clips",
        "videoUrl": "https://cdn/r1.mp4",
        "timestamp": "2026-04-01T00:00:00.000Z",
    }
    post = _normalize_post(raw)

    assert post.post_type == "reel"
    assert post.media[0].media_type == "video"
    assert post.media[0].source_url == "https://cdn/r1.mp4"


def test_reel_stores_cover_at_scrape_time():
    # A reel/video with a displayUrl yields [video@0, cover@sentinel] so the
    # report has a usable cover without re-fetching a stale IG URL later.
    raw = {
        "id": "r2",
        "type": "Video",
        "productType": "clips",
        "videoUrl": "https://cdn/r2.mp4",
        "videoDuration": 8.0,
        "displayUrl": "https://cdn/r2_cover.jpg",
        "timestamp": "2026-04-01T00:00:00.000Z",
    }
    post = _normalize_post(raw)

    assert post.post_type == "reel"
    assert len(post.media) == 2
    assert post.media[0].slide_index == 0
    assert post.media[0].media_type == "video"
    cover = post.media[1]
    assert cover.slide_index == REEL_COVER_SLIDE_INDEX
    assert cover.media_type == "image"
    assert cover.source_url == "https://cdn/r2_cover.jpg"


def test_carousel_video_child_gets_cover():
    # Inside a carousel, a video child also contributes a cover at the sentinel
    # index; image children do not.
    raw = {
        "id": "car1",
        "type": "Sidecar",
        "timestamp": "2026-04-01T00:00:00.000Z",
        "childPosts": [
            {"type": "Image", "displayUrl": "https://cdn/1.jpg"},
            {
                "type": "Video",
                "videoUrl": "https://cdn/2.mp4",
                "videoDuration": 5.0,
                "displayUrl": "https://cdn/2_cover.jpg",
            },
        ],
    }
    post = _normalize_post(raw)

    assert [m.slide_index for m in post.media] == [0, 1, REEL_COVER_SLIDE_INDEX]
    assert [m.media_type for m in post.media] == ["image", "video", "image"]
    assert post.media[2].source_url == "https://cdn/2_cover.jpg"


# -------------------------
# get-leads fallback normalizer (`_normalize_post_fallback`)
# -------------------------

_POSTED = datetime(2026, 4, 1, tzinfo=UTC)


def test_fallback_image_post():
    raw = {
        "postId": "111222333",
        "shortCode": "ABC",
        "mediaType": "image",
        "caption": "hi",
        "url": "https://instagram.com/p/ABC/",
        "displayUrl": "https://cdn/img.jpg",
        "likesCount": 10,
        "commentsCount": 2,
        "dimensions": {"width": 1080, "height": 1080},
    }
    post = _normalize_post_fallback(raw, posted_at=_POSTED)

    assert post.platform_post_id == "111222333"
    assert post.post_type == "image"
    assert post.caption == "hi"
    assert post.like_count == 10
    assert len(post.media) == 1
    assert post.media[0].media_type == "image"
    assert post.media[0].source_url == "https://cdn/img.jpg"
    assert post.media[0].width == 1080


def test_fallback_uses_postId_for_dedupe_key():
    # Regression guard for the May 2026 dedup fix: the fallback must key on the
    # numeric postId (matching the primary's `id`), not the shortCode.
    raw = {
        "postId": "987654321",
        "shortCode": "SHORT",
        "mediaType": "image",
        "displayUrl": "https://cdn/x.jpg",
    }
    post = _normalize_post_fallback(raw, posted_at=_POSTED)
    assert post.platform_post_id == "987654321"


def test_fallback_falls_back_to_shortcode_without_postId():
    raw = {"shortCode": "ONLYSHORT", "mediaType": "image", "displayUrl": "https://cdn/x.jpg"}
    post = _normalize_post_fallback(raw, posted_at=_POSTED)
    assert post.platform_post_id == "ONLYSHORT"


def test_fallback_raises_without_any_id():
    raw = {"mediaType": "image", "displayUrl": "https://cdn/x.jpg"}
    with pytest.raises(ValueError, match="no postId / shortCode"):
        _normalize_post_fallback(raw, posted_at=_POSTED)


def test_fallback_reel_detected_via_play_count():
    raw = {
        "postId": "555",
        "mediaType": "video",
        "videoUrl": "https://cdn/v.mp4",
        "videoDuration": 12.0,
        "videoPlayCount": 9000,
        "videoViewCount": 8000,
        "displayUrl": "https://cdn/v_cover.jpg",
    }
    post = _normalize_post_fallback(raw, posted_at=_POSTED)

    assert post.post_type == "reel"
    assert post.play_count == 9000
    assert post.view_count == 8000
    # Fallback path captures only the cover frame — no scrape-time cover row
    # (see the TODO in _normalize_post_fallback). One media, the video itself.
    assert len(post.media) == 1
    assert post.media[0].media_type == "video"
    assert post.media[0].source_url == "https://cdn/v.mp4"


def test_fallback_carousel_detected_from_media_type():
    raw = {
        "postId": "777",
        "mediaType": "Sidecar",
        "displayUrl": "https://cdn/cover.jpg",
    }
    post = _normalize_post_fallback(raw, posted_at=_POSTED)
    assert post.post_type == "carousel"
