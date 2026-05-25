"""
HikerAPI client — managed SaaS wrapping instagrapi's mobile private API.

We use `api.instagrapi.com` (no-Cloudflare mirror) by default. The Cloudflare
host `api.hikerapi.com` filters on User-Agent; we send a real UA so failing
over by base_url alone would work, but the mirror is more reliable for our
unattended cron use.

This module returns RAW HikerAPI media dicts. Normalization to `ScrapedPost`
lives in `scrapers/instagram.py` next to the existing normalizers — keeps
the per-tier mapping logic in one place.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..logging import get_logger

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.instagrapi.com"
USER_AGENT = "social-bot/1.0"

# IG's natural page size. HikerAPI's /v2/user/medias ignores any `amount`
# hint and always returns ~12; pagination is mandatory for higher limits.
PAGE_SIZE_HINT = 12


class HikerTransient(Exception):
    """5xx / network / timeout. Caller may retry or fall through to Apify."""


class HikerFatal(Exception):
    """Auth, not-found, or permanent client error. Caller should fall through."""


class HikerClient:
    """Thin wrapper around HikerAPI's user-by-username and user-medias endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={
                "x-access-key": api_key,
                "accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "HikerClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def fetch_user_medias(
        self,
        handle: str,
        *,
        limit: int = 30,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch up to `limit` recent posts for `handle`.

        If `user_id` is provided, the username→pk lookup is skipped — saves
        one paid request per run.

        Posts come back newest-first. We stop paginating as soon as the
        oldest item drops below `since_dt` — no point pulling more history
        than the caller asked for.

        Returns:
            List of raw HikerAPI media dicts. Empty list = the account has
            no recent posts in the requested window (NOT an error).

        Raises:
            HikerFatal: handle not found, key invalid, or permanent 4xx
            HikerTransient: 5xx, network, or timeout after one retry
        """
        uid = user_id or self.lookup_user_id(handle)
        return self._paginate_medias(
            uid, limit=limit, since_dt=since_dt, until_dt=until_dt
        )

    def fetch_user_stories(self, *, user_id: str) -> list[dict[str, Any]]:
        """Fetch active story items for an Instagram account by its `pk`.

        Hits `/v2/user/stories/by/id` (the namespace the HikerAPI dashboard
        actually meters us on — `/v2/user/stories`). Returns raw story dicts
        in v2 (instagrapi-v2) shape. Empty list = no active stories (NOT an
        error). Caller is responsible for supplying `user_id`.
        """
        data = self._get("/v2/user/stories", params={"user_id": user_id})
        # v2 shape:
        #   {"broadcast": ..., "reel": {"items": [...], ...} | null, "status": "ok"}
        # `reel == null` means no active stories — return empty list.
        if isinstance(data, dict):
            reel = data.get("reel")
            if isinstance(reel, dict):
                items = reel.get("items")
                if isinstance(items, list):
                    return items
        return []

    def lookup_user_id(self, handle: str) -> str:
        h = handle.lstrip("@")
        data = self._get("/v2/user/by/username", params={"username": h})
        user = (data.get("user") or {}) if isinstance(data, dict) else {}
        pk = user.get("pk") or user.get("id")
        if not pk:
            raise HikerFatal(f"no pk in lookup response for @{h}")
        return str(pk)

    def _paginate_medias(
        self,
        user_id: str,
        *,
        limit: int,
        since_dt: datetime | None,
        until_dt: datetime | None,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page_id: str | None = None
        # +2 buffer covers partial pages and one safety overshoot.
        max_pages = (limit // PAGE_SIZE_HINT) + 2

        for page_idx in range(max_pages):
            params: dict[str, Any] = {"user_id": user_id}
            if page_id:
                params["page_id"] = page_id

            data = self._get("/v2/user/medias", params=params)
            response = data.get("response") if isinstance(data, dict) else None
            items = (response or {}).get("items") or []

            # Skip too-old items but keep paginating through the page —
            # IG mobile feed often returns pinned (older-dated) posts as
            # the FIRST items on page 1, which breaks a "stop on first
            # too-old" heuristic. We only stop paginating when an entire
            # page has zero items in the window.
            page_had_in_window = False
            for it in items:
                ts = it.get("taken_at")
                if ts is not None:
                    dt = _ts_to_datetime(ts)
                    if dt is not None:
                        if until_dt is not None and dt > until_dt:
                            continue
                        if since_dt is not None and dt < since_dt:
                            continue
                page_had_in_window = True
                collected.append(it)
                if len(collected) >= limit:
                    log.info(
                        "hiker.pagination.stop_limit",
                        pages_fetched=page_idx + 1,
                        collected=len(collected),
                    )
                    return collected

            if since_dt is not None and items and not page_had_in_window:
                log.info(
                    "hiker.pagination.stop_since",
                    pages_fetched=page_idx + 1,
                    collected=len(collected),
                )
                return collected

            if not (response or {}).get("more_available"):
                log.info(
                    "hiker.pagination.stop_exhausted",
                    pages_fetched=page_idx + 1,
                    collected=len(collected),
                )
                return collected
            page_id = data.get("next_page_id") or (response or {}).get("next_max_id")
            if not page_id:
                return collected

        log.warning(
            "hiker.pagination.max_pages_hit",
            user_id=user_id,
            collected=len(collected),
        )
        return collected

    def _get(self, path: str, *, params: dict[str, Any]) -> Any:
        """GET with single retry on transient errors. Returns parsed JSON
        (dict for most endpoints; some /v1/ endpoints return lists)."""
        for attempt in (0, 1):
            try:
                r = self._http.get(path, params=params)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                if attempt == 0:
                    log.warning("hiker.transient_network", path=path, error=str(exc))
                    time.sleep(5)
                    continue
                raise HikerTransient(f"{type(exc).__name__}: {exc}") from exc

            status = r.status_code
            if status == 200:
                try:
                    parsed = r.json()
                except ValueError as exc:
                    raise HikerTransient(f"bad JSON: {exc}") from exc
                return parsed

            if status in (401, 403):
                raise HikerFatal(f"auth/key error {status}: {r.text[:200]}")
            if status == 404:
                raise HikerFatal(f"not found 404: {r.text[:200]}")
            if 500 <= status < 600:
                if attempt == 0:
                    log.warning("hiker.5xx", path=path, status=status)
                    time.sleep(5)
                    continue
                raise HikerTransient(f"5xx after retry: {status}")
            # Other 4xx → likely fatal (bad request shape)
            raise HikerFatal(f"unexpected status {status}: {r.text[:200]}")

        raise HikerTransient("retry loop exited unexpectedly")


def _ts_to_datetime(ts: Any) -> datetime | None:
    """HikerAPI's /v2 returns `taken_at` as Unix epoch seconds."""
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
