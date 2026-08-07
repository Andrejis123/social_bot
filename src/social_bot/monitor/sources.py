"""
Thread sources for the watering-hole monitor.

Reddit's JSON API (`/new.json`, `oauth.reddit.com`) is unavailable to us:
unauthenticated JSON is 403 from datacenter IPs AND through a residential
proxy (verified from the VPS, 2026-08-01), and OAuth now requires an approved
Reddit Data API application. The public **RSS** feed still answers anonymously
from the VPS, so that is the v1 transport.

RSS is rate-limited hard: at 20s spacing roughly half the reads come back 429.
`fetch_subreddit` therefore retries with backoff, and a subreddit that never
answers is logged and skipped rather than failing the run — a partial sweep is
worth strictly more than no sweep, and the next run re-reads the same window.

Swapping in OAuth later means adding one `ThreadSource` implementation; nothing
downstream knows where a `Thread` came from.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from xml.etree import ElementTree

import httpx

from ..logging import get_logger

log = get_logger(__name__)

_RSS_URL = "https://www.reddit.com/r/{subreddit}/new.rss"
# A descriptive UA with contact info. Generic UAs are throttled harder, and an
# anonymous scraper with no way to be contacted is what gets IPs banned.
USER_AGENT = "social-bot-monitor/0.1 (market research; contact tomas@agapeslovensko.sk)"

_ATOM = "{http://www.w3.org/2005/Atom}"
# Backoff between attempts for one subreddit. Total worst case ~2min/sub.
_RETRY_DELAYS = (15.0, 30.0, 60.0)
# Politeness gap between two different subreddits, on top of any retries.
INTER_FEED_DELAY = 20.0

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(slots=True)
class Thread:
    """One public thread, source-agnostic."""

    external_id: str        # stable per source, e.g. reddit's 't3_1abc23'
    source: str             # 'reddit'
    channel: str            # subreddit name, no 'r/' prefix
    title: str
    body: str               # plain text, tags stripped; '' for link posts
    url: str
    author: str
    created_at: datetime    # timezone-aware UTC

    @property
    def haystack(self) -> str:
        """Lowercased title + body, the text the keyword filter searches."""
        return f"{self.title}\n{self.body}".lower()


class ThreadSource(Protocol):
    """Anything that can produce recent threads. Implemented by RedditRSSSource;
    an OAuth-backed source drops in here unchanged."""

    def fetch(self, channels: list[str], *, max_age_hours: int) -> list[Thread]: ...


def strip_html(raw: str) -> str:
    """Reddit ships post bodies as escaped HTML. We only need readable text
    for keyword matching and the LLM prompt."""
    text = _TAG_RE.sub(" ", raw)
    for entity, char in (
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
    ):
        text = text.replace(entity, char)
    return _WS_RE.sub(" ", text).strip()


def parse_feed(xml_text: str, *, subreddit: str) -> list[Thread]:
    """Parse a Reddit Atom feed into Threads.

    A single malformed entry is skipped, not fatal: feeds occasionally carry
    a deleted/quarantined item with no link or timestamp, and losing the whole
    subreddit over one bad row would be a silent coverage gap.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        log.warning("monitor.feed.parse_failed", subreddit=subreddit, error=str(exc))
        return []

    threads: list[Thread] = []
    for entry in root.findall(f"{_ATOM}entry"):
        external_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        link_el = entry.find(f"{_ATOM}link")
        url = (link_el.get("href") if link_el is not None else "") or ""
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        published = entry.findtext(f"{_ATOM}published") or entry.findtext(f"{_ATOM}updated")

        if not external_id or not url or not published:
            continue

        created = _parse_ts(published)
        if created is None:
            continue

        author_el = entry.find(f"{_ATOM}author")
        author = ""
        if author_el is not None:
            author = (author_el.findtext(f"{_ATOM}name") or "").strip()

        threads.append(
            Thread(
                external_id=external_id,
                source="reddit",
                channel=subreddit,
                title=title,
                body=strip_html(entry.findtext(f"{_ATOM}content") or ""),
                url=url,
                author=author,
                created_at=created,
            )
        )
    return threads


def _parse_ts(value: str) -> datetime | None:
    """Guarded ISO-8601 parse — a garbage timestamp must never raise."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class RedditRSSSource:
    """Polls public subreddit RSS feeds, newest first."""

    def __init__(self, *, timeout: float = 30.0, sleep: bool = True) -> None:
        self._timeout = timeout
        # Tests disable sleeping; the real run must keep it (rate limits).
        self._sleep = sleep

    def fetch(self, channels: list[str], *, max_age_hours: int) -> list[Thread]:
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        collected: list[Thread] = []
        with httpx.Client(
            timeout=self._timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as http:
            for index, subreddit in enumerate(channels):
                if index and self._sleep:
                    time.sleep(INTER_FEED_DELAY)
                xml_text = self._get_with_retry(http, subreddit)
                if xml_text is None:
                    continue
                fresh = [t for t in parse_feed(xml_text, subreddit=subreddit) if t.created_at >= cutoff]
                log.info("monitor.feed.fetched", subreddit=subreddit, fresh=len(fresh))
                collected.extend(fresh)
        return collected

    def _get_with_retry(self, http: httpx.Client, subreddit: str) -> str | None:
        url = _RSS_URL.format(subreddit=subreddit)
        for attempt, delay in enumerate((0.0, *_RETRY_DELAYS)):
            if delay and self._sleep:
                time.sleep(delay)
            try:
                resp = http.get(url)
            except httpx.HTTPError as exc:
                log.warning("monitor.feed.error", subreddit=subreddit, attempt=attempt, error=str(exc))
                continue
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                # A typo'd or deleted subreddit never recovers; burning the full
                # 105s backoff on it every run is pure dead time.
                log.error("monitor.feed.not_found", subreddit=subreddit)
                return None
            log.warning(
                "monitor.feed.http_error",
                subreddit=subreddit,
                attempt=attempt,
                status=resp.status_code,
            )
        log.error("monitor.feed.gave_up", subreddit=subreddit)
        return None
