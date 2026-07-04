"""
Single cached Supabase client. All DB and Storage calls go through this.

Using the *service* key, which bypasses row-level security. Never expose this
client to a browser / untrusted caller.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache, partial
from itertools import batched
from typing import Any, cast

from supabase import Client, create_client

from ..config import get_settings

# PostgREST silently caps a single response at 1000 rows. Every bulk lister
# must page with .range() until a short page arrives, or results truncate
# silently (incomplete reports, partial archive bundles).
_PAGE_SIZE = 1000

# Chunk size for `.in_()` id filters — keeps the request URL bounded.
_ID_CHUNK = 100


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_key)


def rows(resp: Any) -> list[dict[str, Any]]:
    """Rows from a Supabase select/insert `.execute()` result.

    supabase-py types `APIResponse.data` as a broad JSON union; for every table
    query in this codebase it is in fact a list of row dicts. Cast once here so
    callers can index rows without fighting the union typing. ``None`` data
    (empty result) becomes ``[]``. Formalizes the inline
    ``cast(list[dict], res.data or [])`` idiom already used by the Drive queries.
    """
    return cast("list[dict[str, Any]]", resp.data or [])


def single(resp: Any) -> dict[str, Any] | None:
    """Row from a `.single()` query: `.data` is one row dict, or None if absent."""
    return cast("dict[str, Any] | None", resp.data)


def fetch_all(build_query: Callable[[], Any]) -> list[dict[str, Any]]:
    """Fetch every row of a PostgREST query, paging past the implicit row cap.

    `build_query` must return a FRESH filtered query on each call — builders
    are single-use once executed, so the query is rebuilt per page.
    """
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        res = build_query().range(offset, offset + _PAGE_SIZE - 1).execute()
        page_rows = rows(res)
        out.extend(page_rows)
        if len(page_rows) < _PAGE_SIZE:
            return out
        offset += _PAGE_SIZE


def fetch_all_chunked(
    build_query: Callable[[list[str]], Any], ids: list[str]
) -> list[dict[str, Any]]:
    """fetch_all over an id list, chunking the `.in_()` filter to keep the
    request URL bounded. `build_query(ids_chunk)` must return a fresh query."""
    out: list[dict[str, Any]] = []
    for chunk in batched(ids, _ID_CHUNK):
        out.extend(fetch_all(partial(build_query, list(chunk))))
    return out
