"""Tests for storage.summary — turning a flat path list into a per-account
posts/stories/files breakdown that reconciles against a report.

Path shapes mirror production (storage/media.py, pipeline/ingest_stories.py):
    {client}/{handle}/{platform}/posts/{YYYY}/{MM}/{post_id}/{slide}.{ext}
    {client}/{handle}/{platform}/stories/{YYYY}/{MM}/{DD}/{story_id}.{ext}
"""
from __future__ import annotations

from social_bot.storage.summary import render_summary, summarize_paths


def _post(handle: str, post_id: str, slide: int, ext: str = "jpg") -> str:
    return f"agape/{handle}/instagram/posts/2026/06/{post_id}/{slide}.{ext}"


def _story(handle: str, story_id: str) -> str:
    return f"agape/{handle}/instagram/stories/2026/06/30/{story_id}.mp4"


def test_carousel_and_reel_slides_collapse_to_one_post_each() -> None:
    # A carousel (8 slides) + a reel (mp4 + cover) = 2 posts but 10 files.
    paths = [_post("agapeslovensko", "carousel-1", i) for i in range(8)]
    paths += [
        "agape/agapeslovensko/instagram/posts/2026/06/reel-1/0.mp4",
        "agape/agapeslovensko/instagram/posts/2026/06/reel-1/99.jpg",
    ]
    s = summarize_paths(paths)
    assert s.total_posts == 2
    assert s.total_stories == 0
    assert s.total_files == 10


def test_each_story_file_is_one_story() -> None:
    paths = [_story("agapeslovensko", f"story-{i}") for i in range(15)]
    s = summarize_paths(paths)
    assert s.total_stories == 15
    assert s.total_posts == 0
    assert s.total_files == 15


def test_grouped_per_account() -> None:
    paths = [
        _post("agapeslovensko", "p1", 0),
        _post("agapeslovensko", "p1", 1),  # same post, another slide
        _story("agapeslovensko", "s1"),
        "agape/agape_bratislava/instagram/posts/2026/06/pb1/0.heic",
    ]
    s = summarize_paths(paths)
    slovensko = s.accounts[("agape", "agapeslovensko")]
    bratislava = s.accounts[("agape", "agape_bratislava")]
    assert len(slovensko.posts) == 1
    assert len(slovensko.stories) == 1
    assert slovensko.files == 3
    assert len(bratislava.posts) == 1
    assert bratislava.files == 1


def test_reproduces_real_agape_purge_counts() -> None:
    # The 2026-07-02 agape purge: 40 files = agapeslovensko 9 posts + 15 stories
    # (39 files) and agape_bratislava 1 post (1 file). Must match the report.
    paths = [_story("agapeslovensko", f"s{i}") for i in range(15)]
    for i in range(8):  # 8 reels: mp4 + cover
        paths += [
            f"agape/agapeslovensko/instagram/posts/2026/06/reel{i}/0.mp4",
            f"agape/agapeslovensko/instagram/posts/2026/06/reel{i}/99.jpg",
        ]
    for i in range(8):  # 1 carousel, 8 slides
        paths.append(f"agape/agapeslovensko/instagram/posts/2026/06/carousel/{i}.jpg")
    paths.append("agape/agape_bratislava/instagram/posts/2026/06/pb/0.heic")

    s = summarize_paths(paths)
    assert s.total_files == 40
    assert s.total_posts == 10  # 9 slovensko + 1 bratislava
    assert s.total_stories == 15
    assert s.total_items == 25
    assert len(s.accounts[("agape", "agapeslovensko")].posts) == 9


def test_render_is_singular_plural_correct() -> None:
    paths = [
        "agape/agape_bratislava/instagram/posts/2026/06/pb/0.heic",  # 1 post
    ]
    out = render_summary(summarize_paths(paths), verb="purged")
    assert "@agape_bratislava: 1 post, 0 stories (1 file)" in out
    assert "Total purged: 1 item, 1 file" in out


def test_unrecognised_path_still_counts_as_file() -> None:
    s = summarize_paths(["weird/short/path.jpg"])
    assert s.total_files == 1
    assert s.total_items == 0
    assert s.unclassified_files == 1
