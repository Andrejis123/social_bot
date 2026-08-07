"""
Prompt building + verdict parsing for the stage-2 LLM pass.

No Gemini call here: `build_prompt` and `parse_verdict` are the two pure seams,
and they carry the safety properties that matter — a bounded prompt (cost) and
a clamped score (an out-of-range score would silently defeat the threshold).
"""

from __future__ import annotations

import json

import pytest

from social_bot.monitor.config import DraftStyle
from social_bot.monitor.relevance import (
    build_prompt,
    count_sentences,
    parse_verdict,
    soft_pitch_flags,
)
from tests.fakes import make_thread

DRAFT = DraftStyle(max_sentences=3, voice="casual commenter, no sign-off, no bullet points")


def test_build_prompt_interpolates_every_field() -> None:
    thread = make_thread(
        channel="PPC",
        title="Anyone archiving competitor stories",
        body="they expire in 24h and our tool misses them",
    )
    prompt = build_prompt(thread, draft=DRAFT, min_score=70)

    assert "Subreddit: r/PPC" in prompt
    assert "Title: Anyone archiving competitor stories" in prompt
    assert "Body: they expire in 24h and our tool misses them" in prompt
    assert "at or above 70" in prompt
    assert "Hard limit 3 sentences" in prompt
    assert DRAFT.voice in prompt
    # No unfilled placeholders left behind.
    assert "{" not in prompt


def test_build_prompt_substitutes_placeholder_for_link_post() -> None:
    prompt = build_prompt(make_thread(body=""), draft=DRAFT, min_score=65)
    assert "Body: (link post, no body text)" in prompt


def test_build_prompt_truncates_long_body() -> None:
    thread = make_thread(body="a" * 4500 + "TAIL")
    prompt = build_prompt(thread, draft=DRAFT, min_score=65)

    assert "TAIL" not in prompt
    assert "a" * 4000 in prompt
    assert "a" * 4001 not in prompt


def test_parse_verdict_reads_all_fields() -> None:
    verdict = parse_verdict(
        json.dumps({"score": 82, "reason": "asks about story capture", "draft_reply": "try X"})
    )
    assert verdict.score == 82
    assert verdict.reason == "asks about story capture"
    assert verdict.draft_reply == "try X"


def test_parse_verdict_strips_whitespace() -> None:
    verdict = parse_verdict(
        json.dumps({"score": 10, "reason": "  off topic\n", "draft_reply": "\n  no reply  "})
    )
    assert verdict.reason == "off topic"
    assert verdict.draft_reply == "no reply"


def test_parse_verdict_defaults_missing_text_fields() -> None:
    verdict = parse_verdict('{"score": 50}')
    assert verdict.reason == ""
    assert verdict.draft_reply == ""


def test_parse_verdict_clamps_negative_score() -> None:
    assert parse_verdict('{"score": -20, "reason": "x"}').score == 0


def test_parse_verdict_clamps_score_above_100() -> None:
    assert parse_verdict('{"score": 4200, "reason": "x"}').score == 100


def test_parse_verdict_accepts_boundary_scores() -> None:
    assert parse_verdict('{"score": 0}').score == 0
    assert parse_verdict('{"score": 100}').score == 100


def test_parse_verdict_raises_on_malformed_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_verdict("not json at all")
    with pytest.raises(json.JSONDecodeError):
        parse_verdict("")


def test_parse_verdict_raises_when_score_absent() -> None:
    # A verdict with no score cannot be thresholded; failing loudly is correct.
    with pytest.raises(KeyError):
        parse_verdict('{"reason": "no score field"}')


# soft_pitch_flags ---------------------------------------------------------


def test_soft_pitch_flags_catches_unnamed_tool_nudge() -> None:
    assert soft_pitch_flags("some tools can pull that historical data") == ["some tools"]


def test_soft_pitch_flags_empty_when_tool_is_named_outright() -> None:
    assert soft_pitch_flags("metricool does this natively on the paid plan") == []
    assert soft_pitch_flags("") == []


def test_soft_pitch_flags_is_case_insensitive() -> None:
    assert soft_pitch_flags("There Are Tools for this") == ["there are tools"]
    assert soft_pitch_flags("DM me if you want the script") == ["dm me"]


def test_soft_pitch_flags_returns_every_match_in_pattern_order() -> None:
    text = "i built something for this, my tool handles it, dm me"
    assert soft_pitch_flags(text) == ["i built", "my tool", "dm me"]


def test_soft_pitch_flags_respects_word_boundaries() -> None:
    # "dismembered" contains "dm" but not the phrase; the \b guards must hold.
    assert soft_pitch_flags("undismembered toolset") == []


def test_parse_verdict_populates_flags_from_draft_reply() -> None:
    verdict = parse_verdict(
        json.dumps(
            {"score": 90, "reason": "good fit", "draft_reply": "there are tools that do this"}
        )
    )
    assert verdict.flags == ["there are tools"]


def test_parse_verdict_flags_empty_for_a_clean_draft() -> None:
    verdict = parse_verdict(
        json.dumps({"score": 90, "reason": "good fit", "draft_reply": "metricool does this"})
    )
    assert verdict.flags == []


def test_parse_verdict_flags_empty_when_draft_missing() -> None:
    assert parse_verdict('{"score": 20}').flags == []


# count_sentences ----------------------------------------------------------


def test_count_sentences_multi_sentence() -> None:
    assert count_sentences("Hello world. How are you? Fine!") == 3


def test_count_sentences_ignores_trailing_punctuation() -> None:
    assert count_sentences("one sentence only.") == 1
    assert count_sentences("what about this?!") == 1


def test_count_sentences_without_terminator() -> None:
    assert count_sentences("no punctuation at all") == 1


def test_count_sentences_empty_string_is_zero() -> None:
    assert count_sentences("") == 0
    assert count_sentences("   ") == 0
