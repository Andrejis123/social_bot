"""
Notion queue for reviewed threads.

Notion is the output surface (Andy's call 01-08-2026) because the human step is
the whole point: he has to read the thread, judge it, post a reply in his own
words, and mark it handled. A Telegram digest is one-way and stateless; the
Notion rows double as the dedup store, so a thread surfaced once never comes
back even after it is marked Ignored.

DB: "Watering Hole Queue" — properties Title, URL, Source, Channel, Project,
Score, Reason, Draft reply, Draft flags, Status, Found at, External ID. Notion
400s the whole `push` if any property here is missing from the database, so this
list is the schema contract: adding a property below means adding it in Notion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from ..config import get_settings
from ..logging import get_logger
from .filtering import dedupe_key
from .relevance import Verdict
from .sources import Thread

log = get_logger(__name__)

_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
# Notion rejects rich_text values over 2000 chars with a 400.
_TEXT_CAP = 1900


@dataclass(slots=True)
class QueueClient:
    token: str
    database_id: str
    timeout: float = 30.0

    @classmethod
    def from_settings(cls) -> QueueClient:
        settings = get_settings()
        if not settings.notion_api_token:
            raise RuntimeError("NOTION_API_TOKEN is not set")
        if not settings.watering_hole_db_id:
            raise RuntimeError("WATERING_HOLE_DB_ID is not set")
        return cls(token=settings.notion_api_token, database_id=settings.watering_hole_db_id)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def existing_keys(self) -> set[str]:
        """Every External ID already in the queue, across all statuses.

        Paginated: PostgREST is not the only API in this repo with a silent
        page cap, and a truncated read here would re-queue old threads.
        """
        keys: set[str] = set()
        cursor: str | None = None
        with httpx.Client(timeout=self.timeout, headers=self._headers) as http:
            while True:
                body: dict[str, object] = {"page_size": 100}
                if cursor:
                    body["start_cursor"] = cursor
                resp = http.post(f"{_API}/databases/{self.database_id}/query", json=body)
                resp.raise_for_status()
                payload = resp.json()
                for row in payload.get("results", []):
                    prop = row.get("properties", {}).get("External ID", {})
                    for chunk in prop.get("rich_text", []):
                        keys.add(chunk.get("plain_text", ""))
                cursor = payload.get("next_cursor")
                # `has_more` without a cursor would re-issue the identical
                # unpaginated query forever; stop instead of hanging the run.
                if not payload.get("has_more") or not cursor:
                    return keys

    def push(self, thread: Thread, verdict: Verdict, *, project: str) -> str:
        """Create one queue row. Returns the new page id."""
        properties = {
            "Title": {"title": [{"text": {"content": thread.title[:_TEXT_CAP] or "(no title)"}}]},
            "URL": {"url": thread.url},
            "Source": {"select": {"name": thread.source}},
            "Channel": {"rich_text": [{"text": {"content": thread.channel}}]},
            "Project": {"select": {"name": project}},
            "Score": {"number": verdict.score},
            "Reason": {"rich_text": [{"text": {"content": verdict.reason[:_TEXT_CAP]}}]},
            "Draft reply": {"rich_text": [{"text": {"content": verdict.draft_reply[:_TEXT_CAP]}}]},
            # Non-empty = the draft contains covert-advertising phrasing and
            # must be rewritten before posting. Shown at review time, which is
            # the only moment the warning can still change what happens.
            "Draft flags": {
                "rich_text": [
                    {"text": {"content": ("soft pitch: " + ", ".join(verdict.flags))[:_TEXT_CAP]}}
                ]
                if verdict.flags
                else []
            },
            "Status": {"select": {"name": "New"}},
            "Found at": {"date": {"start": datetime.now(UTC).isoformat()}},
            "External ID": {"rich_text": [{"text": {"content": dedupe_key(thread)}}]},
        }
        with httpx.Client(timeout=self.timeout, headers=self._headers) as http:
            resp = http.post(
                f"{_API}/pages",
                json={"parent": {"database_id": self.database_id}, "properties": properties},
            )
            resp.raise_for_status()
            page_id: str = resp.json()["id"]
        log.info("monitor.queue.pushed", url=thread.url, score=verdict.score, page=page_id[:8])
        return page_id
