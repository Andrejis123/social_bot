"""
Summarise a set of storage paths by account, splitting files from items.

Archive and purge both operate on lists of object paths, but a raw file count
is hard to reconcile against a report: a single carousel post or reel is several
files (slides + cover), and a story is one file. This turns a flat path list
into a per-account breakdown of distinct posts, distinct stories, and total
files, so a purge/archive summary lines up with the report's per-account counts.

Path schemes (see storage/media.py and pipeline/ingest_stories.py):
    {client}/{handle}/{platform}/posts/{YYYY}/{MM}/{post_id}/{slide}.{ext}
    {client}/{handle}/{platform}/stories/{YYYY}/{MM}/{DD}/{story_id}.{ext}
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


def summarize_paths(paths: Iterable[str]) -> StorageSummary:
    """Group storage paths into a per-account posts/stories/files breakdown.

    Every path counts toward a file total. Paths whose shape we recognise also
    contribute their distinct parent item (post_id or story_id). Unrecognised
    shapes are still counted as files (so the file total always matches the
    number of objects purged) but add no item.
    """
    summary = StorageSummary()
    for path in paths:
        parts = path.split("/")
        # Minimum recognised shape: client/handle/platform/kind/.../item
        if len(parts) < 8:
            summary.unclassified_files += 1
            continue
        client, handle, _platform, kind = parts[0], parts[1], parts[2], parts[3]
        acct = summary.accounts.get((client, handle))
        if acct is None:
            acct = AccountBreakdown(handle=handle)
            summary.accounts[(client, handle)] = acct
        acct.files += 1
        if kind == "posts":
            acct.posts.add(parts[6])  # {post_id}
        elif kind == "stories":
            acct.stories.add(parts[-1].rsplit(".", 1)[0])  # {story_id}
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
