"""
Stage-1 keyword gate tests.

Note the contract: `KeywordSet` terms must already be lowercase (the loader
lowercases them) and `Thread.haystack` lowercases the text, so matching is
case-insensitive with respect to the thread, not the terms.
"""

from __future__ import annotations

from social_bot.monitor.config import KeywordSet
from social_bot.monitor.filtering import dedupe_key, matches, prefilter
from tests.fakes import make_thread

KEYWORDS = KeywordSet(project="Social_Bot", any=["competitor", "story archive"], none=["hiring"])


def test_matches_is_plain_substring() -> None:
    assert matches("we track competitors monthly", ["competitor"]) is True
    assert matches("we track competitors monthly", ["metricool"]) is False
    assert matches("anything", []) is False


def test_prefilter_keeps_thread_matching_any_term() -> None:
    thread = make_thread(title="Best way to track a COMPETITOR", body="")
    result = prefilter([thread], KEYWORDS)

    assert result.kept == [thread]
    assert result.dropped_no_match == 0
    assert result.dropped_vetoed == 0


def test_prefilter_matches_on_body_too() -> None:
    thread = make_thread(title="Monthly deliverables", body="Story Archive for each client")
    assert prefilter([thread], KEYWORDS).kept == [thread]


def test_prefilter_drops_thread_with_no_match() -> None:
    thread = make_thread(title="How do I grow my account", body="posting daily, no traction")
    result = prefilter([thread], KEYWORDS)

    assert result.kept == []
    assert result.dropped_no_match == 1
    assert result.dropped_vetoed == 0


def test_veto_beats_an_any_hit() -> None:
    thread = make_thread(title="Hiring someone to track a competitor", body="")
    result = prefilter([thread], KEYWORDS)

    assert result.kept == []
    assert result.dropped_no_match == 0
    assert result.dropped_vetoed == 1


def test_veto_term_alone_is_not_enough_to_count_as_vetoed() -> None:
    # No `any` hit, so the thread never reaches the veto stage.
    thread = make_thread(title="Hiring a junior media buyer", body="")
    result = prefilter([thread], KEYWORDS)

    assert result.dropped_no_match == 1
    assert result.dropped_vetoed == 0


def test_empty_none_list_vetoes_nothing() -> None:
    keywords = KeywordSet(project="Social_Bot", any=["competitor"], none=[])
    thread = make_thread(title="hiring help with competitor research", body="")
    result = prefilter([thread], keywords)

    assert result.kept == [thread]
    assert result.dropped_vetoed == 0


def test_examined_sums_all_three_buckets() -> None:
    threads = [
        make_thread(external_id="t3_a", title="competitor tracking", body=""),
        make_thread(external_id="t3_b", title="competitor tracking", body=""),
        make_thread(external_id="t3_c", title="hiring a competitor analyst", body=""),
        make_thread(external_id="t3_d", title="best time to post", body=""),
    ]
    result = prefilter(threads, KEYWORDS)

    assert len(result.kept) == 2
    assert result.dropped_vetoed == 1
    assert result.dropped_no_match == 1
    assert result.examined == 4


def test_prefilter_on_empty_input() -> None:
    result = prefilter([], KEYWORDS)
    assert result.kept == []
    assert result.examined == 0
    assert result.dropped_titles == []


def test_dropped_titles_collects_both_drop_reasons_in_feed_order() -> None:
    threads = [
        make_thread(external_id="t3_a", title="best time to post", body=""),
        make_thread(external_id="t3_b", title="competitor tracking stack", body=""),
        make_thread(external_id="t3_c", title="hiring a competitor analyst", body=""),
        make_thread(external_id="t3_d", title="how do I grow my account", body=""),
    ]
    result = prefilter(threads, KEYWORDS)

    # One no-match, one vetoed, one no-match — interleaved, and the list must
    # follow feed order rather than group by reason.
    assert result.dropped_titles == [
        "best time to post",
        "hiring a competitor analyst",
        "how do I grow my account",
    ]
    assert len(result.dropped_titles) == result.dropped_no_match + result.dropped_vetoed


def test_dropped_titles_empty_when_everything_is_kept() -> None:
    result = prefilter([make_thread(title="competitor research help")], KEYWORDS)
    assert result.dropped_titles == []


def test_dedupe_key_prefixes_source() -> None:
    assert dedupe_key(make_thread(source="reddit", external_id="t3_abc123")) == "reddit:t3_abc123"
    assert dedupe_key(make_thread(source="forum", external_id="t3_abc123")) == "forum:t3_abc123"
