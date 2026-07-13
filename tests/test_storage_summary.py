"""Tests for storage.summary — summarizing (kind, item_id, storage_path) items
into a per-account posts/stories/files breakdown that reconciles against a report.

Item identity is COLUMN-derived: each item is a (kind, item_id, storage_path)
tuple where kind is "post" or "story" and item_id comes from the DB row
(media.post_id / story_media.story_id), so the counts no longer depend on
positional path parsing. Paths still drive the per-account grouping
((client, handle) = first two segments, requiring at least 4 segments) and
the file totals.

Path shapes mirror production (storage/media.py, pipeline/ingest_stories.py):
    {client}/{handle}/{platform}/posts/{YYYY}/{MM}/{post_id}/{slide}.{ext}
    {client}/{handle}/{platform}/stories/{YYYY}/{MM}/{DD}/{story_id}.{ext}
"""
from __future__ import annotations

from social_bot.storage.summary import render_summary


def _summarize(items):
    # Local import so a missing summarize_items fails the test, not collection.
    from social_bot.storage.summary import summarize_items

    return summarize_items(items)


def _post_item(handle: str, post_id: str, slide: int, ext: str = "jpg"):
    return (
        "post",
        post_id,
        f"agape/{handle}/instagram/posts/2026/06/{post_id}/{slide}.{ext}",
    )


def _story_item(handle: str, story_id: str):
    return (
        "story",
        story_id,
        f"agape/{handle}/instagram/stories/2026/06/30/{story_id}.mp4",
    )


def test_carousel_and_reel_slides_collapse_to_one_post_each() -> None:
    # A carousel (8 slides) + a reel (mp4 + cover) = 2 posts but 10 files.
    items = [_post_item("agapeslovensko", "carousel-1", i) for i in range(8)]
    items += [
        ("post", "reel-1", "agape/agapeslovensko/instagram/posts/2026/06/reel-1/0.mp4"),
        ("post", "reel-1", "agape/agapeslovensko/instagram/posts/2026/06/reel-1/99.jpg"),
    ]
    s = _summarize(items)
    assert s.total_posts == 2
    assert s.total_stories == 0
    assert s.total_files == 10


def test_each_story_is_one_story() -> None:
    items = [_story_item("agapeslovensko", f"story-{i}") for i in range(15)]
    s = _summarize(items)
    assert s.total_stories == 15
    assert s.total_posts == 0
    assert s.total_files == 15


def test_grouped_per_account() -> None:
    items = [
        _post_item("agapeslovensko", "p1", 0),
        _post_item("agapeslovensko", "p1", 1),  # same post, another slide
        _story_item("agapeslovensko", "s1"),
        ("post", "pb1", "agape/agape_bratislava/instagram/posts/2026/06/pb1/0.heic"),
    ]
    s = _summarize(items)
    slovensko = s.accounts[("agape", "agapeslovensko")]
    bratislava = s.accounts[("agape", "agape_bratislava")]
    assert len(slovensko.posts) == 1
    assert len(slovensko.stories) == 1
    assert slovensko.files == 3
    assert len(bratislava.posts) == 1
    assert bratislava.files == 1


def test_none_item_id_counts_file_but_no_item() -> None:
    # A row missing its post_id still counts toward the account's file total
    # (the file total must match the number of objects purged) but adds no item.
    items = [
        ("post", None, "agape/agapeslovensko/instagram/posts/2026/06/p1/0.jpg"),
        _post_item("agapeslovensko", "p2", 0),
    ]
    s = _summarize(items)
    acct = s.accounts[("agape", "agapeslovensko")]
    assert acct.files == 2
    assert len(acct.posts) == 1  # only p2; None added nothing
    assert s.total_items == 1
    assert s.total_files == 2
    assert s.unclassified_files == 0


def test_short_path_is_unclassified_even_with_item_id() -> None:
    # Under 4 segments there is no (client, handle) to group by: the file is
    # counted as unclassified and contributes no account and no item.
    s = _summarize([("post", "p1", "weird/short/path.jpg")])
    assert s.total_files == 1
    assert s.total_items == 0
    assert s.unclassified_files == 1
    assert s.accounts == {}


def test_item_counts_survive_path_layout_old_parser_misreads() -> None:
    # KEY regression: the old positional parser took the post_id from a fixed
    # path segment (parts[6]) and the story_id from the filename stem. A layout
    # with an extra directory level (e.g. a TikTok slideshow "slides" dir) made
    # every post collapse into one, and a story split into per-file "stories".
    # Column-derived item ids must not care about path layout at all.
    items = [
        # Two DISTINCT posts sharing the same parts[6] ("slides"):
        ("post", "P1", "agape/h1/tiktok/posts/2026/06/slides/P1/0.jpg"),
        ("post", "P1", "agape/h1/tiktok/posts/2026/06/slides/P1/1.jpg"),
        ("post", "P2", "agape/h1/tiktok/posts/2026/06/slides/P2/0.jpg"),
        # One story whose files have index filenames (stem is NOT the story id):
        ("story", "S1", "agape/h1/instagram/stories/2026/06/30/S1/0.mp4"),
        ("story", "S1", "agape/h1/instagram/stories/2026/06/30/S1/1.mp4"),
    ]
    s = _summarize(items)
    acct = s.accounts[("agape", "h1")]
    assert len(acct.posts) == 2  # P1 + P2, not 1 collapsed "slides" post
    assert len(acct.stories) == 1  # S1, not 2 filename-stem stories
    assert acct.files == 5
    assert s.total_items == 3


def test_reproduces_real_agape_purge_counts() -> None:
    # The 2026-07-02 agape purge: 40 files = agapeslovensko 9 posts + 15 stories
    # (39 files) and agape_bratislava 1 post (1 file). Must match the report.
    items = [_story_item("agapeslovensko", f"s{i}") for i in range(15)]
    for i in range(8):  # 8 reels: mp4 + cover
        items += [
            ("post", f"reel{i}",
             f"agape/agapeslovensko/instagram/posts/2026/06/reel{i}/0.mp4"),
            ("post", f"reel{i}",
             f"agape/agapeslovensko/instagram/posts/2026/06/reel{i}/99.jpg"),
        ]
    for i in range(8):  # 1 carousel, 8 slides
        items.append(
            ("post", "carousel",
             f"agape/agapeslovensko/instagram/posts/2026/06/carousel/{i}.jpg")
        )
    items.append(
        ("post", "pb", "agape/agape_bratislava/instagram/posts/2026/06/pb/0.heic")
    )

    s = _summarize(items)
    assert s.total_files == 40
    assert s.total_posts == 10  # 9 slovensko + 1 bratislava
    assert s.total_stories == 15
    assert s.total_items == 25
    assert len(s.accounts[("agape", "agapeslovensko")].posts) == 9


def test_render_is_singular_plural_correct() -> None:
    items = [
        ("post", "pb", "agape/agape_bratislava/instagram/posts/2026/06/pb/0.heic"),
    ]
    out = render_summary(_summarize(items), verb="purged")
    assert "@agape_bratislava: 1 post, 0 stories (1 file)" in out
    assert "Total purged: 1 item, 1 file" in out


def test_render_includes_unclassified_line() -> None:
    items = [
        ("post", "pb", "agape/agape_bratislava/instagram/posts/2026/06/pb/0.heic"),
        ("post", "x", "too/short.jpg"),
    ]
    out = render_summary(_summarize(items), verb="purged")
    assert "unclassified: 1 file" in out
    assert "Total purged: 1 item, 2 files" in out
