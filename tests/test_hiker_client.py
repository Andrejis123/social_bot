"""
HikerClient._get retry behaviour.

HikerAPI intermittently returns 404 UserNotFound for valid accounts. In the
stories path we retry once on a 404 before giving up (an intermittent
UserNotFound is really transient), while the default posts path keeps the
fail-fast behaviour. These tests lock that contract in.
"""

from __future__ import annotations

from typing import Any

import pytest

from social_bot.scrapers import _hiker_client
from social_bot.scrapers._hiker_client import HikerClient, HikerFatal, HikerTransient


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
    """Stands in for the httpx.Client; returns queued responses in order.

    Queue entries may also be exceptions (e.g. httpx.ConnectError), which are
    raised instead of returned — mirrors transport-level failures.
    """

    def __init__(self, responses: list[_Resp | Exception]):
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, path: str, params: dict | None = None) -> _Resp:
        self.calls += 1
        self.requests.append((path, params))
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_hiker_client.time, "sleep", lambda *_a, **_k: None)


def _client(responses: list[_Resp | Exception]) -> tuple[HikerClient, _FakeHttp]:
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


# -------------------------
# fetch_stories_by_username — single-call stories fetch
# (live-verified shapes, 09-07-2026)
# -------------------------

# Shaped like the live endpoint's reel.user (trimmed).
_USER = {
    "pk": 1820756068,
    "id": "1820756068",
    "username": "dennikn",
    "full_name": "Dennik N",
    "is_verified": True,
    "is_private": False,
}
_ITEMS = [{"pk": 1}, {"pk": 2}]


def _reel_ok() -> _Resp:
    return _Resp(200, {"reel": {"user": _USER, "items": _ITEMS}, "status": "ok"})


def test_fetch_stories_hits_by_username_endpoint_and_strips_handle() -> None:
    c, fake = _client([_reel_ok()])
    user, items = c.fetch_stories_by_username(" @dennikn ")
    assert user == _USER
    assert items == _ITEMS
    assert fake.calls == 1
    path, params = fake.requests[0]
    assert path == "/v2/user/stories/by/username"
    assert params == {"username": "dennikn"}  # @ and whitespace stripped


def test_fetch_stories_reel_null_is_success_with_single_call() -> None:
    # {"reel": null, "status": "ok"} = zero active stories. SUCCESS, not an
    # error: single call, no retry burn, no exception.
    c, fake = _client([_Resp(200, {"reel": None, "status": "ok"})])
    assert c.fetch_stories_by_username("dennikn") == ({}, [])
    assert fake.calls == 1


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (["not", "a", "dict"], ({}, [])),
        ({"status": "ok"}, ({}, [])),
        ({"reel": "garbage", "status": "ok"}, ({}, [])),
        ({"reel": {"user": _USER, "no_items_key": True}}, (_USER, [])),
        ({"reel": {"user": _USER, "items": "not-a-list"}}, (_USER, [])),
        ({"reel": {"items": _ITEMS}}, ({}, _ITEMS)),  # user missing -> empty dict
        ({"reel": {"user": "not-a-dict", "items": _ITEMS}}, ({}, _ITEMS)),
    ],
)
def test_fetch_stories_malformed_shapes_are_defensive(
    payload: Any, expected: tuple[dict[str, Any], list[dict[str, Any]]]
) -> None:
    c, _ = _client([_Resp(200, payload)])
    assert c.fetch_stories_by_username("dennikn") == expected


def test_fetch_stories_retries_once_on_404_then_succeeds() -> None:
    c, fake = _client([_Resp(404, text="User not found"), _reel_ok()])
    assert c.fetch_stories_by_username("dennikn") == (_USER, _ITEMS)
    assert fake.calls == 2


def test_fetch_stories_404_twice_is_fatal() -> None:
    c, fake = _client([_Resp(404, text="nope"), _Resp(404, text="nope")])
    with pytest.raises(HikerFatal):
        c.fetch_stories_by_username("dennikn")
    assert fake.calls == 2


@pytest.mark.parametrize("status", [401, 403])
def test_fetch_stories_auth_errors_are_fatal_without_retry(status: int) -> None:
    c, fake = _client([_Resp(status, text="bad key")])
    with pytest.raises(HikerFatal):
        c.fetch_stories_by_username("dennikn")
    assert fake.calls == 1


def test_fetch_stories_5xx_then_200_succeeds() -> None:
    c, fake = _client([_Resp(503, text="upstream"), _reel_ok()])
    assert c.fetch_stories_by_username("dennikn") == (_USER, _ITEMS)
    assert fake.calls == 2


def test_fetch_stories_5xx_twice_is_transient() -> None:
    c, fake = _client([_Resp(500, text="boom"), _Resp(502, text="boom")])
    with pytest.raises(HikerTransient):
        c.fetch_stories_by_username("dennikn")
    assert fake.calls == 2


def test_old_fetch_user_stories_is_removed() -> None:
    assert not hasattr(HikerClient, "fetch_user_stories")
