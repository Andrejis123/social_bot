"""
Telegram notification formatting tests.

No network: get_settings is stubbed so the token/chat gate passes, and
httpx.Client is replaced with a recorder that captures the sendMessage
payload. Contract: messages use parse_mode=HTML, so any dynamic value
interpolated into the text (error strings especially — tracebacks contain
'<' and '&') must be HTML-escaped or Telegram 400s, send() swallows the
failure, and the ops alert is silently lost. Intended markup written by
the module itself (<b>, <code>) must survive untouched.
"""

from __future__ import annotations

from social_bot.notifications import telegram

RAW_ERROR = "<b>boom & crash</b>"
ESCAPED_ERROR = "&lt;b&gt;boom &amp; crash&lt;/b&gt;"


class _FakeSettings:
    telegram_bot_token = "test-token"
    telegram_chat_id = "12345"


def _patch(monkeypatch):
    """Stub settings + httpx; return the list of captured post payloads."""
    posted: list[dict] = []

    class _Resp:
        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, data=None, **kwargs):
            posted.append(data or {})
            return _Resp()

    monkeypatch.setattr(telegram, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(telegram.httpx, "Client", _FakeClient)
    return posted


def _assert_escaped(posted: list[dict]) -> None:
    assert len(posted) == 1
    text = posted[0]["text"]
    assert ESCAPED_ERROR in text, f"error not HTML-escaped in: {text!r}"
    assert "<b>boom" not in text
    # The module's own markup must remain real tags.
    assert "<b>" in text


# RED: bug 7 — passes once notify_report_failed html-escapes the error string.
def test_notify_report_failed_escapes_error(monkeypatch):
    posted = _patch(monkeypatch)
    telegram.notify_report_failed(
        client_slug="testclient", period_label="April 2026", error=RAW_ERROR
    )
    _assert_escaped(posted)


# RED: bug 7 — passes once notify_archive_failed html-escapes the error string.
def test_notify_archive_failed_escapes_error(monkeypatch):
    posted = _patch(monkeypatch)
    telegram.notify_archive_failed(client_slug="testclient", error=RAW_ERROR)
    _assert_escaped(posted)


# RED: bug 7 — passes once notify_purge_failed html-escapes the error string.
def test_notify_purge_failed_escapes_error(monkeypatch):
    posted = _patch(monkeypatch)
    telegram.notify_purge_failed(client_label="testclient", error=RAW_ERROR)
    _assert_escaped(posted)
