"""
Pure-function tests for the Instagram normalizer.

No network, no Supabase, no Apify — just feeds synthetic payloads through the
shape detection + field mapping logic. If Apify changes its output schema,
update the fixtures here first and the normalizer follows.
"""

from __future__ import annotations

from social_bot.scrapers.instagram import _normalize_post


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
