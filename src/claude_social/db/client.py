"""
Single cached Supabase client. All DB and Storage calls go through this.

Using the *service* key, which bypasses row-level security. Never expose this
client to a browser / untrusted caller.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from ..config import get_settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_key)
