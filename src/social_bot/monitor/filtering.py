"""
Stage-1 keyword filter.

Free and deliberately generous: r/marketing alone would swamp the LLM stage if
every thread went through, but a too-tight regex would silently hide the
threads worth answering. `prefilter` returns the survivors AND the drop count
so the CLI can log what was thrown away — a filter that quietly matches nothing
looks exactly like a quiet week.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import KeywordSet
from .sources import Thread


@dataclass(slots=True)
class PrefilterResult:
    kept: list[Thread]
    dropped_no_match: int
    dropped_vetoed: int
    # Titles of dropped threads, in feed order. Kept so the CLI can print a
    # sample: a filter eating real signal is indistinguishable from a quiet
    # week unless you can see what it threw away.
    dropped_titles: list[str] = field(default_factory=list)

    @property
    def examined(self) -> int:
        return len(self.kept) + self.dropped_no_match + self.dropped_vetoed


def matches(text: str, terms: list[str]) -> bool:
    """Substring match, case-insensitive. `text` must already be lowercased."""
    return any(term in text for term in terms)


def prefilter(threads: list[Thread], keywords: KeywordSet) -> PrefilterResult:
    kept: list[Thread] = []
    dropped_titles: list[str] = []
    no_match = 0
    vetoed = 0
    for thread in threads:
        haystack = thread.haystack
        if not matches(haystack, keywords.any):
            no_match += 1
            dropped_titles.append(thread.title)
            continue
        if keywords.none and matches(haystack, keywords.none):
            vetoed += 1
            dropped_titles.append(thread.title)
            continue
        kept.append(thread)
    return PrefilterResult(
        kept=kept,
        dropped_no_match=no_match,
        dropped_vetoed=vetoed,
        dropped_titles=dropped_titles,
    )


def dedupe_key(thread: Thread) -> str:
    """Stable identity for a thread across runs.

    Reddit ids are already globally unique, but prefixing with the source keeps
    the key correct once a second source exists (a forum's numeric post id
    would otherwise be free to collide).
    """
    return f"{thread.source}:{thread.external_id}"
