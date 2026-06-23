"""
Facebook post normalizer — fixture-driven regression guard.

Fixtures are real anonymous captures of apify/facebook-posts-scraper:
  - facebook_official_agape.json : the real monitoring target (reel-heavy + 1 photo)
  - facebook_official_nasa.json  : variety the target lacks (text-only, carousel)

These assert the mapping from the actor's raw item -> our ScrapedPost shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from social_bot.scrapers.facebook import _normalize_post_facebook

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> list[dict]:
    data = json.loads((FIXTURES / name).read_text())
    return [p for p in data if isinstance(p, dict) and p.get("postId")]


def _find(name: str, post_id: str) -> dict:
    for item in _load(name):
        if item.get("postId") == post_id:
            return item
    raise AssertionError(f"{post_id} not in {name}")


# --------- Reel (video) ---------


def test_reel_maps_video_metrics_and_cover() -> None:
    post = _normalize_post_facebook(_find("facebook_official_agape.json", "1064573886232516"))
    assert post.platform == "facebook"
    assert post.platform_post_id == "1064573886232516"
    assert post.post_type == "reel"  # url contains /reel/
    assert post.caption is not None and post.caption.startswith("Vymyslel Boh")
    # likes field is the reaction TOTAL (16+5+1 style); maps straight to like_count
    assert post.like_count == 260
    assert post.comment_count == 23
    assert post.share_count == 43
    assert post.view_count == 5273
    assert post.save_count is None  # FB has no saves
    # Anonymous capture exposes only the cover image, not a playable mp4.
    assert len(post.media) == 1
    assert post.media[0].media_type == "image"
    assert post.media[0].source_url.startswith("https://")
    assert post.permalink == "https://www.facebook.com/100080397431532/posts/1064573886232516"
    assert post.posted_at is not None
    assert (post.posted_at.year, post.posted_at.month, post.posted_at.day) == (2026, 6, 22)


# --------- Single photo ---------


def test_single_photo_is_image() -> None:
    post = _normalize_post_facebook(_find("facebook_official_agape.json", "1026391916717380"))
    assert post.post_type == "image"
    assert post.like_count == 22
    assert post.comment_count == 3
    assert post.share_count == 3
    assert post.view_count is None
    assert len(post.media) == 1
    assert post.media[0].media_type == "image"
    assert post.media[0].source_url.startswith("https://")


# --------- Carousel (filters the junk media[0]) ---------


def test_carousel_filters_unusable_media() -> None:
    post = _normalize_post_facebook(_find("facebook_official_nasa.json", "1537227674439270"))
    assert post.post_type == "carousel"
    # Raw has 4 media items; the first is a junk element with no source URL.
    assert len(post.media) == 3
    assert all(m.media_type == "image" for m in post.media)
    assert all(m.source_url.startswith("https://") for m in post.media)
    assert [m.slide_index for m in post.media] == [0, 1, 2]


# --------- Text-only (no media) ---------


def test_text_only_post_has_empty_media() -> None:
    post = _normalize_post_facebook(_find("facebook_official_nasa.json", "1550510099777694"))
    assert post.post_type == "text"
    assert post.media == []
    assert post.platform == "facebook"


# --------- raw is preserved ---------


def test_raw_payload_preserved() -> None:
    raw = _find("facebook_official_agape.json", "1064573886232516")
    post = _normalize_post_facebook(raw)
    assert post.raw == raw
