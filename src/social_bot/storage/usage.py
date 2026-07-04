"""Bucket storage usage breakdown.

Walks the Supabase Storage media bucket and sums every object's real size,
grouped by client and by kind (posts vs stories). This is the only authoritative
view of what occupies the 1 GB free-tier file-storage cap: `story_media` rows
carry no `bytes` column, so the DB cannot answer "how big are the stories" — the
bucket can. The Supabase dashboard only shows a lagging billing-period average,
not a current point-in-time per-folder breakdown.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..config import get_settings
from ..db.client import get_supabase

_PAGE = 100


@dataclass(slots=True)
class StorageBreakdown:
    total_bytes: int = 0
    total_files: int = 0
    # (client, kind) -> [bytes, files]. Per-client totals are derived from this.
    by_client_kind: dict[tuple[str, str], list[int]] = field(default_factory=dict)


def _walk(prefix: str = ""):
    """Yield (path, size_bytes) for every object under prefix (recursive)."""
    sb = get_supabase()
    bucket = get_settings().supabase_media_bucket
    offset = 0
    while True:
        items = sb.storage.from_(bucket).list(prefix, {"limit": _PAGE, "offset": offset})
        if not items:
            return
        for it in items:
            full = f"{prefix}/{it['name']}" if prefix else it["name"]
            meta = it.get("metadata")
            if meta and meta.get("size") is not None:
                yield full, int(meta["size"])
            else:
                yield from _walk(full)  # it's a folder
        if len(items) < _PAGE:
            return
        offset += _PAGE


def list_object_paths(prefix: str = "") -> list[str]:
    """Return every object path under prefix in the media bucket (recursive).

    The authoritative, row-independent view of what physically occupies the
    bucket. Used by the orphan sweep to find objects no DB row points at.
    """
    return [path for path, _size in _walk(prefix)]


def compute_storage_breakdown() -> StorageBreakdown:
    b = StorageBreakdown()
    by_kind: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for path, size in _walk():
        b.total_bytes += size
        b.total_files += 1
        parts = path.split("/")
        client = parts[0]
        kind = "stories" if "stories" in parts else ("posts" if "posts" in parts else "other")
        by_kind[(client, kind)][0] += size
        by_kind[(client, kind)][1] += 1
    b.by_client_kind = dict(by_kind)
    return b


def format_storage_breakdown(b: StorageBreakdown, *, cap_gb: float = 1.0) -> str:
    def gb(n: int) -> str:
        return f"{n / 1e9:.3f} GB"

    pct = b.total_bytes / 1e9 / cap_gb * 100 if cap_gb else 0
    by_client: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (client, _kind), (bytes_, files) in b.by_client_kind.items():
        by_client[client][0] += bytes_
        by_client[client][1] += files

    lines = [
        "## Storage breakdown (bucket, point-in-time)",
        "",
        f"**Total: {gb(b.total_bytes)} / {cap_gb:g} GB ({pct:.0f}%)** "
        f"across {b.total_files} files",
        "",
        "| Client | Size | Files |",
        "|--------|------|-------|",
    ]
    for client, (bytes_, files) in sorted(by_client.items(), key=lambda x: -x[1][0]):
        lines.append(f"| {client} | {gb(bytes_)} | {files} |")
    lines += ["", "| Client | Kind | Size | Files |", "|--------|------|------|-------|"]
    for (client, kind), (bytes_, files) in sorted(
        b.by_client_kind.items(), key=lambda x: -x[1][0]
    ):
        lines.append(f"| {client} | {kind} | {gb(bytes_)} | {files} |")
    return "\n".join(lines)
