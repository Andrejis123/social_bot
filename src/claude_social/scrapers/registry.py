"""
Platform → Scraper registry.

Adding a new platform: implement the `Scraper` protocol and register it here.
"""

from __future__ import annotations

from .base import Scraper
from .instagram import InstagramScraper

_REGISTRY: dict[str, type[Scraper]] = {
    "instagram": InstagramScraper,
}


def get_scraper(platform: str) -> Scraper:
    try:
        cls = _REGISTRY[platform]
    except KeyError as exc:
        raise ValueError(
            f"No scraper registered for platform {platform!r}. "
            f"Registered: {sorted(_REGISTRY)}"
        ) from exc
    return cls()


def supported_platforms() -> list[str]:
    return sorted(_REGISTRY)
