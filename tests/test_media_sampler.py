"""Tests for the AI media sampler."""

from __future__ import annotations

from claude_social.ai.media_sampler import pick_for_ai
from claude_social.scrapers.base import ScrapedMedia, ScrapedPost


def _post(post_type: str, n: int) -> ScrapedPost:
    return ScrapedPost(
        platform="instagram",
        platform_post_id="x",
        post_type=post_type,
        caption=None,
        permalink=None,
        posted_at=None,
        media=[
            ScrapedMedia(
                slide_index=i,
                media_type="image",
                source_url=f"https://cdn/{i}.jpg",
            )
            for i in range(n)
        ],
    )


def test_single_image_returns_one():
    assert len(pick_for_ai(_post("image", 1))) == 1


def test_small_carousel_returns_all():
    assert [m.slide_index for m in pick_for_ai(_post("carousel", 3))] == [0, 1, 2]


def test_large_carousel_samples_first_middle_last():
    picked = pick_for_ai(_post("carousel", 10))
    assert [m.slide_index for m in picked] == [0, 5, 9]


def test_drops_media_with_empty_source_url():
    post = _post("carousel", 3)
    post.media[1].source_url = ""
    picked = pick_for_ai(post)
    assert [m.slide_index for m in picked] == [0, 2]
