"""Tests for the AI media sampler."""

from __future__ import annotations

from social_bot.ai.media_sampler import pick_for_ai, sample_media
from social_bot.scrapers.base import REEL_COVER_SLIDE_INDEX, ScrapedMedia, ScrapedPost


def _sample_media_rows(rows: list[dict]) -> list[dict]:
    """How describe/retry jobs sample DB media rows (via the shared sampler)."""
    return sample_media(rows, lambda r: r.get("slide_index"))


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


def test_reel_cover_dropped_when_video_present():
    # A reel is [video, sentinel cover]; the cover is a keyframe of the video
    # already being sent, so only the video goes to the AI.
    post = _post("reel", 1)
    post.media[0].media_type = "video"
    post.media.append(ScrapedMedia(
        slide_index=REEL_COVER_SLIDE_INDEX,
        media_type="image",
        source_url="https://cdn/cover.jpg",
    ))
    picked = pick_for_ai(post)
    assert [m.slide_index for m in picked] == [0]


def test_reel_cover_kept_when_only_media():
    # Video URL missing entirely: the cover is all we have, keep it.
    post = _post("reel", 0)
    post.media.append(ScrapedMedia(
        slide_index=REEL_COVER_SLIDE_INDEX,
        media_type="image",
        source_url="https://cdn/cover.jpg",
    ))
    picked = pick_for_ai(post)
    assert [m.slide_index for m in picked] == [REEL_COVER_SLIDE_INDEX]


def test_describe_sampling_drops_reel_cover_row():
    rows = [
        {"slide_index": 0, "media_type": "video", "storage_path": "a/0.mp4"},
        {"slide_index": REEL_COVER_SLIDE_INDEX, "media_type": "image", "storage_path": "a/99.jpg"},
    ]
    assert [r["slide_index"] for r in _sample_media_rows(rows)] == [0]


def test_describe_sampling_keeps_cover_when_only_row():
    rows = [
        {"slide_index": REEL_COVER_SLIDE_INDEX, "media_type": "image", "storage_path": "a/99.jpg"},
    ]
    assert [r["slide_index"] for r in _sample_media_rows(rows)] == [REEL_COVER_SLIDE_INDEX]
