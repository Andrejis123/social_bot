"""
Reddit RSS parsing tests for the watering-hole monitor.

No network: `parse_feed` is fed Atom XML strings shaped like the real
r/<sub>/new.rss payload. The contract that matters is resilience — a feed with
one deleted or timestamp-less entry must still yield the good entries, and a
truncated body of XML must yield an empty list rather than sink the run.
"""

from __future__ import annotations

from datetime import UTC, datetime

from social_bot.monitor.sources import _parse_ts, parse_feed, strip_html

ENTRY = """  <entry>
    <id>{id}</id>
    <link href="{url}"/>
    <title>{title}</title>
    <updated>{updated}</updated>
    <published>{published}</published>
    <content type="html">{content}</content>
    <author><name>{author}</name></author>
  </entry>
"""


def _entry(
    *,
    id_: str = "t3_abc123",
    url: str = "https://www.reddit.com/r/marketing/comments/abc123/x/",
    title: str = "Tracking competitor stories",
    published: str = "2026-08-01T09:00:00+00:00",
    updated: str = "2026-08-01T09:05:00+00:00",
    content: str = "&lt;p&gt;we archive them by hand&lt;/p&gt;",
    author: str = "/u/someone",
) -> str:
    return ENTRY.format(
        id=id_,
        url=url,
        title=title,
        published=published,
        updated=updated,
        content=content,
        author=author,
    )


def _feed(*entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <title>marketing</title>\n" + "".join(entries) + "</feed>\n"
    )


# strip_html ---------------------------------------------------------------


def test_strip_html_removes_tags_and_collapses_whitespace() -> None:
    raw = "<div class='md'>\n  <p>hello</p>\n\n  <p>world</p>\n</div>"
    assert strip_html(raw) == "hello world"


def test_strip_html_unescapes_known_entities() -> None:
    raw = "<p>tools &amp; reports &quot;monthly&quot; &#39;client&#39;&nbsp;work &lt;3</p>"
    assert strip_html(raw) == "tools & reports \"monthly\" 'client' work <3"


def test_strip_html_on_empty_string() -> None:
    assert strip_html("") == ""


# _parse_ts ----------------------------------------------------------------


def test_parse_ts_handles_z_suffix() -> None:
    assert _parse_ts("2026-08-01T09:00:00Z") == datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def test_parse_ts_converts_offset_to_utc() -> None:
    assert _parse_ts("2026-08-01T11:00:00+02:00") == datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def test_parse_ts_assumes_utc_for_naive_input() -> None:
    parsed = _parse_ts("2026-08-01T09:00:00")
    assert parsed == datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    assert parsed is not None and parsed.tzinfo is UTC


def test_parse_ts_returns_none_on_garbage() -> None:
    assert _parse_ts("not a date") is None
    assert _parse_ts("") is None


# parse_feed ---------------------------------------------------------------


def test_parse_feed_populates_every_field() -> None:
    threads = parse_feed(_feed(_entry()), subreddit="marketing")

    assert len(threads) == 1
    thread = threads[0]
    assert thread.external_id == "t3_abc123"
    assert thread.source == "reddit"
    assert thread.channel == "marketing"
    assert thread.title == "Tracking competitor stories"
    assert thread.body == "we archive them by hand"
    assert thread.url == "https://www.reddit.com/r/marketing/comments/abc123/x/"
    assert thread.author == "/u/someone"
    assert thread.created_at == datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def test_parse_feed_returns_empty_list_on_malformed_xml() -> None:
    assert parse_feed("<feed><entry><id>t3_x</id>", subreddit="marketing") == []
    assert parse_feed("", subreddit="marketing") == []


def test_parse_feed_skips_entry_without_id() -> None:
    broken = """  <entry>
    <link href="https://example.com/a"/>
    <title>no id here</title>
    <published>2026-08-01T09:00:00+00:00</published>
  </entry>
"""
    threads = parse_feed(_feed(broken, _entry()), subreddit="marketing")
    assert [t.external_id for t in threads] == ["t3_abc123"]


def test_parse_feed_skips_entry_without_link() -> None:
    broken = """  <entry>
    <id>t3_nolink</id>
    <title>deleted post</title>
    <published>2026-08-01T09:00:00+00:00</published>
  </entry>
"""
    threads = parse_feed(_feed(broken, _entry()), subreddit="marketing")
    assert [t.external_id for t in threads] == ["t3_abc123"]


def test_parse_feed_skips_entry_without_timestamp() -> None:
    broken = """  <entry>
    <id>t3_nots</id>
    <link href="https://example.com/a"/>
    <title>no timestamp</title>
  </entry>
"""
    threads = parse_feed(_feed(broken, _entry()), subreddit="marketing")
    assert [t.external_id for t in threads] == ["t3_abc123"]


def test_parse_feed_skips_entry_with_unparseable_timestamp() -> None:
    threads = parse_feed(
        _feed(_entry(id_="t3_bad", published="yesterday-ish"), _entry()),
        subreddit="marketing",
    )
    assert [t.external_id for t in threads] == ["t3_abc123"]


def test_parse_feed_falls_back_to_updated_when_published_missing() -> None:
    entry = """  <entry>
    <id>t3_upd</id>
    <link href="https://example.com/a"/>
    <title>only updated</title>
    <updated>2026-08-01T10:30:00+00:00</updated>
  </entry>
"""
    threads = parse_feed(_feed(entry), subreddit="marketing")
    assert threads[0].created_at == datetime(2026, 8, 1, 10, 30, tzinfo=UTC)


def test_parse_feed_keeps_entry_with_empty_title_and_body() -> None:
    entry = """  <entry>
    <id>t3_bare</id>
    <link href="https://example.com/a"/>
    <published>2026-08-01T09:00:00+00:00</published>
  </entry>
"""
    threads = parse_feed(_feed(entry), subreddit="marketing")
    assert len(threads) == 1
    assert threads[0].title == ""
    assert threads[0].body == ""
    assert threads[0].author == ""


def test_parse_feed_returns_all_entries_in_order() -> None:
    threads = parse_feed(
        _feed(_entry(id_="t3_one"), _entry(id_="t3_two"), _entry(id_="t3_three")),
        subreddit="PPC",
    )
    assert [t.external_id for t in threads] == ["t3_one", "t3_two", "t3_three"]
    assert {t.channel for t in threads} == {"PPC"}


def test_thread_haystack_lowercases_title_and_body() -> None:
    thread = parse_feed(
        _feed(_entry(title="Tracking COMPETITOR Stories", content="Sprout Social IS pricey")),
        subreddit="marketing",
    )[0]
    assert thread.haystack == "tracking competitor stories\nsprout social is pricey"
