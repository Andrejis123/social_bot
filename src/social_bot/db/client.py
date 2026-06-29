"""
Single cached Supabase client. All DB and Storage calls go through this.

Using the *service* key, which bypasses row-level security. Never expose this
client to a browser / untrusted caller.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from supabase import Client, create_client

from ..config import get_settings


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
