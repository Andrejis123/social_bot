"""
HikerClient._get retry behaviour.

HikerAPI intermittently returns 404 UserNotFound for valid accounts. In the
stories path we retry once on a 404 before giving up (an intermittent
UserNotFound is really transient), while the default posts path keeps the
fail-fast behaviour. These tests lock that contract in.
"""

from __future__ import annotations

import pytest

from social_bot.scrapers import _hiker_client
from social_bot.scrapers._hiker_client import HikerClient, HikerFatal


class _Resp:
    def __init__(self, status: int, payload: object | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class _FakeHttp:
    """Stands in for the httpx.Client; returns queued responses in order."""

    def __init__(self, responses: list[_Resp]):
        self._responses = list(responses)
        self.calls = 0

    def get(self, path: str, params: dict | None = None) -> _Resp:
        self.calls += 1
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_hiker_client.time, "sleep", lambda *_a, **_k: None)


def _client(responses: list[_Resp]) -> tuple[HikerClient, _FakeHttp]:
    c = HikerClient("test-key")
    fake = _FakeHttp(responses)
    c._http = fake  # type: ignore[assignment]
    return c, fake


def test_get_retries_once_on_404_when_enabled() -> None:
    c, fake = _client([_Resp(404, text="User not found"), _Resp(200, {"ok": True})])
    result = c._get("/v2/user/stories", params={"user_id": "1"}, retry_on_404=True)
    assert result == {"ok": True}
    assert fake.calls == 2  # one 404, one retry that succeeded


def test_get_404_fails_fast_by_default() -> None:
    c, fake = _client([_Resp(404, text="User not found")])
    with pytest.raises(HikerFatal):
        c._get("/v2/user/medias", params={"user_id": "1"})
    assert fake.calls == 1  # no retry on the default (posts) path


def test_get_404_retry_exhausted_raises_fatal() -> None:
    c, fake = _client([_Resp(404, text="nope"), _Resp(404, text="nope")])
    with pytest.raises(HikerFatal):
        c._get("/v2/user/stories", params={"user_id": "1"}, retry_on_404=True)
    assert fake.calls == 2


def test_fetch_user_stories_retries_on_404() -> None:
    # First call 404s, retry returns a valid (empty) stories payload.
    c, fake = _client([_Resp(404, text="User not found"), _Resp(200, {"reel": None})])
    stories = c.fetch_user_stories(user_id="123")
    assert stories == []
    assert fake.calls == 2
