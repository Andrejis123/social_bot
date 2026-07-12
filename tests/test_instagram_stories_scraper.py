"""
InstagramScraper stories tier 1 (HikerAPI) — single-call fetch semantics.

Locks the contract of _scrape_stories_hiker after the by-username refactor:
one GET /v2/user/stories/by/username per run returns both the account dict
(reel.user) and the story items. lookup_user_id is called ONLY on the
first-ever scrape of a storyless account (reel null AND no cached pk), purely
to seed discovered_platform_account_id.
"""

from __future__ import annotations

from typing import Any

from social_bot.scrapers.instagram import InstagramScraper

_USER = {"pk": 1820756068, "id": "1820756068", "username": "dennikn"}


def _story_item(pk: int) -> dict[str, Any]:
    return {
        "pk": pk,
        "media_type": 1,
        "taken_at": 1751900000,
        "expiring_at": 1751986400,
        "thumbnail_url": f"https://cdn.example/story-{pk}.jpg",
        "original_width": 1080,
        "original_height": 1920,
    }


class _FakeHiker:
    """Stands in for HikerClient; records calls, serves canned payloads."""

    def __init__(
        self,
        *,
        user: dict[str, Any],
        items: list[dict[str, Any]],
        lookup_pk: str = "999",
    ) -> None:
        self._user = user
        self._items = items
        self._lookup_pk = lookup_pk
        self.fetch_calls: list[str] = []
        self.lookup_calls: list[tuple[str, bool]] = []

    def fetch_stories_by_username(
        self, username: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self.fetch_calls.append(username)
        return self._user, self._items

    def lookup_user_id(self, handle: str, *, retry_on_404: bool = False) -> str:
        self.lookup_calls.append((handle, retry_on_404))
        return self._lookup_pk


def _scraper(fake: _FakeHiker) -> InstagramScraper:
    """InstagramScraper without settings/ApifyClient side effects."""
    s = object.__new__(InstagramScraper)
    s._hiker = fake
    s.discovered_platform_account_id = None
    return s


def test_active_stories_cache_pk_from_reel_user_without_lookup() -> None:
    fake = _FakeHiker(user=_USER, items=[_story_item(1), _story_item(2)])
    s = _scraper(fake)

    stories = s.scrape_stories("dennikn", platform_account_id=None)

    assert [st.platform_story_id for st in stories] == ["1", "2"]
    assert fake.fetch_calls == ["dennikn"]
    assert fake.lookup_calls == []  # pk came from reel.user, no paid lookup
    assert s.discovered_platform_account_id == "1820756068"


def test_reel_null_first_scrape_seeds_pk_via_single_lookup() -> None:
    # First-ever scrape of a storyless account: reel null AND no cached pk.
    # Exactly one lookup_user_id(retry_on_404=True) to seed the cache.
    fake = _FakeHiker(user={}, items=[], lookup_pk="424242")
    s = _scraper(fake)

    stories = s.scrape_stories("dennikn", platform_account_id=None)

    assert stories == []
    assert fake.fetch_calls == ["dennikn"]
    assert fake.lookup_calls == [("dennikn", True)]
    assert s.discovered_platform_account_id == "424242"


def test_reel_null_with_cached_pk_makes_no_lookup() -> None:
    fake = _FakeHiker(user={}, items=[])
    s = _scraper(fake)

    stories = s.scrape_stories("dennikn", platform_account_id="777")

    assert stories == []
    assert fake.fetch_calls == ["dennikn"]
    assert fake.lookup_calls == []  # cached pk, zero extra paid calls
    assert s.discovered_platform_account_id == "777"


def test_one_bad_item_does_not_kill_the_batch() -> None:
    bad = {"media_type": 1}  # no pk/id -> normalizer raises ValueError
    fake = _FakeHiker(user=_USER, items=[_story_item(1), bad, _story_item(3)])
    s = _scraper(fake)

    stories = s.scrape_stories("dennikn", platform_account_id=None)

    assert [st.platform_story_id for st in stories] == ["1", "3"]


def test_seed_lookup_failure_does_not_discard_empty_result() -> None:
    # The stories fetch already succeeded ("no active stories"); a failing
    # pk-seed lookup must not escape _scrape_stories_hiker — it would trigger
    # a paid Apify fallthrough for an account known to have no stories.
    from social_bot.scrapers._hiker_client import HikerFatal

    class _SeedFailHiker(_FakeHiker):
        def lookup_user_id(self, handle: str, *, retry_on_404: bool = False) -> str:
            self.lookup_calls.append((handle, retry_on_404))
            raise HikerFatal("intermittent 404")

    fake = _SeedFailHiker(user={}, items=[])
    s = _scraper(fake)
    assert s.scrape_stories("dennikn") == []
    assert fake.lookup_calls == [("dennikn", True)]
    assert s.discovered_platform_account_id is None
