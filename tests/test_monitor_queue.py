"""
Notion queue client tests.

No network: httpx.Client is replaced with a recorder that returns canned
payloads. Two properties carry real risk — a truncated `existing_keys()` read
would re-queue threads Andy already handled, and a rich_text value over
Notion's 2000-char limit 400s the whole push.
"""

from __future__ import annotations

import pytest

from social_bot.monitor import queue as queue_mod
from social_bot.monitor.queue import _TEXT_CAP, QueueClient
from social_bot.monitor.relevance import Verdict
from tests.fakes import make_thread


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _patch_http(monkeypatch, payloads: list[dict]) -> list[tuple[str, dict]]:
    """Replace httpx.Client; return the list of (url, json body) sent."""
    sent: list[tuple[str, dict]] = []
    queued = list(payloads)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.init_kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, **kwargs):
            sent.append((url, json or {}))
            return _Resp(queued.pop(0))

    monkeypatch.setattr(queue_mod.httpx, "Client", _FakeClient)
    return sent


def _row(external_id: str) -> dict:
    return {"properties": {"External ID": {"rich_text": [{"plain_text": external_id}]}}}


# existing_keys ------------------------------------------------------------


def test_existing_keys_follows_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _patch_http(
        monkeypatch,
        [
            {
                "results": [_row("reddit:t3_a"), _row("reddit:t3_b")],
                "has_more": True,
                "next_cursor": "cursor-2",
            },
            {"results": [_row("reddit:t3_c")], "has_more": False, "next_cursor": None},
        ],
    )

    keys = QueueClient(token="tok", database_id="db123").existing_keys()

    assert keys == {"reddit:t3_a", "reddit:t3_b", "reddit:t3_c"}
    assert len(sent) == 2
    assert sent[0][0] == "https://api.notion.com/v1/databases/db123/query"
    assert "start_cursor" not in sent[0][1]
    assert sent[1][1]["start_cursor"] == "cursor-2"
    assert sent[1][1]["page_size"] == 100


def test_existing_keys_single_page(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _patch_http(monkeypatch, [{"results": [_row("reddit:t3_a")], "has_more": False}])

    assert QueueClient(token="tok", database_id="db123").existing_keys() == {"reddit:t3_a"}
    assert len(sent) == 1


def test_existing_keys_empty_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, [{"results": [], "has_more": False}])
    assert QueueClient(token="tok", database_id="db123").existing_keys() == set()


def test_existing_keys_sends_auth_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, **kwargs):
            return _Resp({"results": [], "has_more": False})

    monkeypatch.setattr(queue_mod.httpx, "Client", _FakeClient)
    QueueClient(token="tok", database_id="db123").existing_keys()

    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["headers"]["Notion-Version"] == "2022-06-28"


# push ---------------------------------------------------------------------


def test_push_builds_notion_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _patch_http(monkeypatch, [{"id": "page-id-0001"}])
    thread = make_thread(
        external_id="t3_abc123",
        channel="marketing",
        title="Tracking competitor stories",
        url="https://www.reddit.com/r/marketing/comments/abc123/x/",
    )
    verdict = Verdict(score=88, reason="asks about story capture", draft_reply="try the export")

    page_id = QueueClient(token="tok", database_id="db123").push(
        thread, verdict, project="Social_Bot"
    )

    assert page_id == "page-id-0001"
    url, body = sent[0]
    assert url == "https://api.notion.com/v1/pages"
    assert body["parent"] == {"database_id": "db123"}

    props = body["properties"]
    assert props["Title"]["title"][0]["text"]["content"] == "Tracking competitor stories"
    assert props["URL"]["url"] == thread.url
    assert props["Source"]["select"]["name"] == "reddit"
    assert props["Channel"]["rich_text"][0]["text"]["content"] == "marketing"
    assert props["Project"]["select"]["name"] == "Social_Bot"
    assert props["Score"]["number"] == 88
    assert props["Reason"]["rich_text"][0]["text"]["content"] == "asks about story capture"
    assert props["Draft reply"]["rich_text"][0]["text"]["content"] == "try the export"
    assert props["Status"]["select"]["name"] == "New"
    assert props["External ID"]["rich_text"][0]["text"]["content"] == "reddit:t3_abc123"
    assert props["Found at"]["date"]["start"].endswith("+00:00")


def test_push_truncates_long_text_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _patch_http(monkeypatch, [{"id": "page-id-0002"}])
    verdict = Verdict(score=70, reason="r" * 2500, draft_reply="d" * 2500)

    QueueClient(token="tok", database_id="db123").push(
        make_thread(title="t" * 2500), verdict, project="Social_Bot"
    )

    props = sent[0][1]["properties"]
    assert len(props["Reason"]["rich_text"][0]["text"]["content"]) == _TEXT_CAP
    assert len(props["Draft reply"]["rich_text"][0]["text"]["content"]) == _TEXT_CAP
    assert len(props["Title"]["title"][0]["text"]["content"]) == _TEXT_CAP
    assert _TEXT_CAP == 1900


def test_push_sends_empty_draft_flags_for_a_clean_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _patch_http(monkeypatch, [{"id": "page-id-0004"}])
    verdict = Verdict(score=70, reason="ok", draft_reply="metricool does this", flags=[])

    QueueClient(token="tok", database_id="db123").push(
        make_thread(), verdict, project="Social_Bot"
    )

    assert sent[0][1]["properties"]["Draft flags"]["rich_text"] == []


def test_push_sends_joined_draft_flags_when_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _patch_http(monkeypatch, [{"id": "page-id-0005"}])
    verdict = Verdict(
        score=70,
        reason="ok",
        draft_reply="some tools do this, dm me",
        flags=["some tools", "dm me"],
    )

    QueueClient(token="tok", database_id="db123").push(
        make_thread(), verdict, project="Social_Bot"
    )

    flags = sent[0][1]["properties"]["Draft flags"]["rich_text"]
    assert flags[0]["text"]["content"] == "soft pitch: some tools, dm me"


def test_push_truncates_draft_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _patch_http(monkeypatch, [{"id": "page-id-0006"}])
    verdict = Verdict(score=70, reason="ok", draft_reply="x", flags=["f" * 40] * 100)

    QueueClient(token="tok", database_id="db123").push(
        make_thread(), verdict, project="Social_Bot"
    )

    content = sent[0][1]["properties"]["Draft flags"]["rich_text"][0]["text"]["content"]
    assert len(content) == _TEXT_CAP


def test_push_falls_back_when_title_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _patch_http(monkeypatch, [{"id": "page-id-0003"}])

    QueueClient(token="tok", database_id="db123").push(
        make_thread(title=""), Verdict(score=70, reason="", draft_reply=""), project="Social_Bot"
    )

    props = sent[0][1]["properties"]
    assert props["Title"]["title"][0]["text"]["content"] == "(no title)"


# from_settings ------------------------------------------------------------


class _FakeSettings:
    def __init__(self, token: str | None, db_id: str | None):
        self.notion_api_token = token
        self.watering_hole_db_id = db_id


def test_from_settings_builds_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_mod, "get_settings", lambda: _FakeSettings("tok", "db123"))
    client = QueueClient.from_settings()
    assert client.token == "tok"
    assert client.database_id == "db123"


def test_from_settings_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_mod, "get_settings", lambda: _FakeSettings(None, "db123"))
    with pytest.raises(RuntimeError, match="NOTION_API_TOKEN"):
        QueueClient.from_settings()


def test_from_settings_requires_db_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_mod, "get_settings", lambda: _FakeSettings("tok", None))
    with pytest.raises(RuntimeError, match="WATERING_HOLE_DB_ID"):
        QueueClient.from_settings()
