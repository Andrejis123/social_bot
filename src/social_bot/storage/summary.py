"""
Summarise archived/purged media by account, splitting files from items.

Archive and purge both operate on lists of storage objects, but a raw file
count is hard to reconcile against a report: a single carousel post or reel is
several files (slides + cover), and a story is one file. This turns a flat list
of (kind, item_id, path) entries into a per-account breakdown of distinct
posts, distinct stories, and total files, so a purge/archive summary lines up
with the report's per-account counts.

Item identity (kind + item_id) comes from DB columns (media.post_id /
story_media.story_id) — never parsed out of the path, so item counts are
immune to path-scheme changes. Only the account grouping is path-derived
({client}/{handle}/... prefix), because handle lives nowhere on the media rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class AccountBreakdown:
    handle: str
    posts: set[str] = field(default_factory=set)
    stories: set[str] = field(default_factory=set)
    files: int = 0


@dataclass
class StorageSummary:
    accounts: dict[tuple[str, str], AccountBreakdown] = field(default_factory=dict)
    unclassified_files: int = 0

    @property
    def total_files(self) -> int:
        return sum(a.files for a in self.accounts.values()) + self.unclassified_files

    @property
    def total_posts(self) -> int:
        return sum(len(a.posts) for a in self.accounts.values())

    @property
    def total_stories(self) -> int:
        return sum(len(a.stories) for a in self.accounts.values())

    @property
    def total_items(self) -> int:
        return self.total_posts + self.total_stories


def summarize_items(items: Iterable[tuple[str, str | None, str]]) -> StorageSummary:
    """Group (kind, item_id, storage_path) entries into a per-account breakdown.

    ``kind`` is "post" or "story"; ``item_id`` is the parent post_id/story_id
    straight from the media row (None contributes no item). Every entry counts
    toward a file total, so the file total always matches the number of objects
    archived/purged. Paths too short to carry a {client}/{handle}/ prefix are
    counted as unclassified files and add no item.
    """
    summary = StorageSummary()
    for kind, item_id, path in items:
        parts = path.split("/")
        # 4 = the shortest shape where parts[0]/parts[1] can plausibly be a
        # {client}/{handle}/ prefix with content below it. All real writers
        # produce 8-segment paths; shorter ones only occur on legacy or
        # hand-inserted rows, where a wrong account line beats losing the file
        # from the totals.
        if len(parts) < 4:
            summary.unclassified_files += 1
            continue
        client, handle = parts[0], parts[1]
        acct = summary.accounts.get((client, handle))
        if acct is None:
            acct = AccountBreakdown(handle=handle)
            summary.accounts[(client, handle)] = acct
        acct.files += 1
        if item_id is None:
            continue
        if kind == "post":
            acct.posts.add(item_id)
        elif kind == "story":
            acct.stories.add(item_id)
    return summary


def render_summary(summary: StorageSummary, *, verb: str) -> str:
    """Plain-text per-account breakdown, e.g.

        @agapeslovensko: 9 posts, 15 stories (40 files)
        @agape_bratislava: 1 post, 0 stories (1 file)
        Total: 10 items, 41 files
    """
    def _plural(n: int, singular: str, plural: str) -> str:
        return f"{n} {singular if n == 1 else plural}"

    lines: list[str] = []
    for acct in sorted(summary.accounts.values(), key=lambda a: a.handle):
        lines.append(
            f"@{acct.handle}: {_plural(len(acct.posts), 'post', 'posts')}, "
            f"{_plural(len(acct.stories), 'story', 'stories')} "
            f"({_plural(acct.files, 'file', 'files')})"
        )
    if summary.unclassified_files:
        lines.append(
            f"unclassified: {_plural(summary.unclassified_files, 'file', 'files')}"
        )
    lines.append(
        f"Total {verb}: {_plural(summary.total_items, 'item', 'items')}, "
        f"{_plural(summary.total_files, 'file', 'files')}"
    )
    return "\n".join(lines)
