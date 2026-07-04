"""
Parsing + error-handling tests for the Gemini provider.

No network, no real API key: we monkeypatch `genai.Client` so
`generate_content` returns canned response text (or raises a canned error),
and stub `get_settings` so the key check passes. This locks the contract of
how Gemini's JSON response becomes a ClassifyResult / description string, and
how transient vs. fatal errors are handled.
"""

from __future__ import annotations

import json

import pytest
from google.genai import errors as genai_errors

from social_bot.ai.providers import gemini
from social_bot.ai.providers.gemini import (
    ClassifyResult,
    _coerce_float,
    classify_with_gemini,
    describe_with_gemini,
)


class _FakeSettings:
    gemini_api_key = "test-key"
    gemini_model = "fake-model"


def _patch(monkeypatch, *, outcomes, api_key="test-key"):
    """Patch the provider so generate_content yields each outcome in turn.

    Each outcome is either a str (used as response.text) or an Exception
    (raised on that call). The last outcome repeats if called again.
    Returns a dict tracking the call count.
    """
    calls = {"n": 0}

    class _Models:
        def generate_content(self, **kwargs):
            i = calls["n"]
            calls["n"] += 1
            out = outcomes[min(i, len(outcomes) - 1)]
            if isinstance(out, Exception):
                raise out
            return type("_Resp", (), {"text": out})()

    class _Client:
        def __init__(self, *args, **kwargs):
            self.models = _Models()

    settings = _FakeSettings()
    settings.gemini_api_key = api_key
    monkeypatch.setattr(gemini.genai, "Client", _Client)
    monkeypatch.setattr(gemini, "get_settings", lambda: settings)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)  # no real backoff
    return calls


# -------------------------
# classify_with_gemini — happy paths
# -------------------------


def test_classify_parses_full_json(monkeypatch):
    _patch(
        monkeypatch,
        outcomes=['{"category": "News", "confidence": 0.9, "reasoning": "because"}'],
    )
    result = classify_with_gemini(prompt="p", media=[], categories=["News", "Ads"])
    assert isinstance(result, ClassifyResult)
    assert result.category == "News"
    assert result.confidence == 0.9
    assert result.reasoning == "because"
    assert result.provider == "gemini"


def test_classify_missing_optional_fields(monkeypatch):
    # Only the required `category` is present.
    _patch(monkeypatch, outcomes=['{"category": "News"}'])
    result = classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert result.category == "News"
    assert result.confidence is None
    assert result.reasoning is None


def test_classify_confidence_string_is_coerced(monkeypatch):
    _patch(monkeypatch, outcomes=['{"category": "News", "confidence": "0.5"}'])
    result = classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert result.confidence == 0.5


def test_classify_bad_confidence_becomes_none(monkeypatch):
    _patch(monkeypatch, outcomes=['{"category": "News", "confidence": "high"}'])
    result = classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert result.confidence is None


# -------------------------
# classify_with_gemini — error handling
# -------------------------


def test_classify_no_api_key_raises(monkeypatch):
    _patch(monkeypatch, outcomes=['{"category": "News"}'], api_key=None)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        classify_with_gemini(prompt="p", media=[], categories=["News"])


def test_classify_malformed_json_propagates(monkeypatch):
    # Not transient (no 429/503 markers) → re-raised, not retried.
    calls = _patch(monkeypatch, outcomes=["this is not json"])
    with pytest.raises(json.JSONDecodeError):
        classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert calls["n"] == 1  # no retry on a fatal parse error


def test_classify_missing_required_category_raises(monkeypatch):
    _patch(monkeypatch, outcomes=['{"confidence": 0.9}'])
    with pytest.raises(KeyError):
        classify_with_gemini(prompt="p", media=[], categories=["News"])


def test_classify_retries_on_transient_then_succeeds(monkeypatch):
    calls = _patch(
        monkeypatch,
        outcomes=[
            _CodedAPIError(503, "503 UNAVAILABLE"),
            '{"category": "News", "confidence": 1.0}',
        ],
    )
    result = classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert result.category == "News"
    assert calls["n"] == 2  # one failure, one success


def test_classify_fatal_error_not_retried(monkeypatch):
    calls = _patch(monkeypatch, outcomes=[RuntimeError("400 INVALID_ARGUMENT")])
    with pytest.raises(RuntimeError, match="400"):
        classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert calls["n"] == 1


# -------------------------
# classify_with_gemini — retry gate must key on the exception code, not on
# substrings of str(exc) (a 400 whose message merely mentions "429" is fatal;
# a 503 whose message lacks the marker words is transient). Reference
# implementation: reports.synthesis._generate_with_retry.
# -------------------------


class _CodedAPIError(genai_errors.APIError):
    """APIError whose str() is only the message, with no status/code text."""

    def __init__(self, code: int, message: str):
        super().__init__(code, {"error": {"message": message, "status": "X"}})

    def __str__(self) -> str:
        return self.message or ""


# RED: bug 8 — passes once the retry gate reads exc.code/status_code instead
# of substring-matching str(exc).
def test_classify_retries_coded_503_without_marker_text(monkeypatch):
    calls = _patch(
        monkeypatch,
        outcomes=[
            _CodedAPIError(503, "service melted down"),  # no 503/429/marker in str()
            '{"category": "News", "confidence": 1.0}',
        ],
    )
    result = classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert result.category == "News"
    assert calls["n"] == 2  # transient by code -> retried once, then succeeded


# RED: bug 8 — passes once the retry gate reads exc.code/status_code instead
# of substring-matching str(exc).
def test_classify_coded_400_mentioning_429_is_not_retried(monkeypatch):
    calls = _patch(
        monkeypatch,
        outcomes=[_CodedAPIError(400, "field must be one of 429 categories")],
    )
    with pytest.raises(genai_errors.APIError):
        classify_with_gemini(prompt="p", media=[], categories=["News"])
    assert calls["n"] == 1  # fatal by code -> raised immediately, no retries


# -------------------------
# describe_with_gemini
# -------------------------


def test_describe_parses_description(monkeypatch):
    _patch(monkeypatch, outcomes=['{"description": "A sunny beach reel."}'])
    out = describe_with_gemini(prompt="p", media=[])
    assert out == "A sunny beach reel."


def test_describe_coerces_non_string(monkeypatch):
    _patch(monkeypatch, outcomes=['{"description": 123}'])
    out = describe_with_gemini(prompt="p", media=[])
    assert out == "123"


def test_describe_missing_field_raises(monkeypatch):
    _patch(monkeypatch, outcomes=['{"summary": "wrong key"}'])
    with pytest.raises(KeyError):
        describe_with_gemini(prompt="p", media=[])


# -------------------------
# _coerce_float (pure helper)
# -------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (0.5, 0.5),
        (1, 1.0),
        ("0.75", 0.75),
        ("nonsense", None),
        ([], None),
    ],
)
def test_coerce_float(value, expected):
    assert _coerce_float(value) == expected
