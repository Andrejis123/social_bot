"""
Data health reporting: per-account scraping volume and AI pass rates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from .db.client import get_supabase
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class AccountHealth:
    handle: str
    account_id: str
    platform: str
    # Posts
    posts_new: int = 0
    posts_classified: int = 0
    posts_classify_fp: int = 0   # classify succeeded first try (ai_attempts = 0)
    posts_described: int = 0
    posts_describe_fp: int = 0   # describe succeeded first try (ai_description_attempts = 0)
    posts_describe_oai: int = 0  # describe used OpenAI fallback
    post_runs_total: int = 0
    post_runs_empty: int = 0
    # Stories
    stories_new: int = 0
    stories_classified: int = 0
    stories_classify_fp: int = 0
    stories_described: int = 0
    stories_describe_fp: int = 0
    story_runs_total: int = 0
    story_runs_empty: int = 0


def parse_interval(token: str) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    token = token.strip().lower()
    if token == "yesterday":
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return today - timedelta(days=1), today
    if token == "7d":
        return now - timedelta(days=7), now
    if token == "30d":
        return now - timedelta(days=30), now
    if token == "90d":
        return now - timedelta(days=90), now
    raise ValueError(f"Unknown interval {token!r}. Use: yesterday, 7d, 30d, 90d")


def _cnt(q) -> int:
    return q.limit(0).execute().count or 0


def _posts(sb, acct_id: str, start: datetime, end: datetime):
    return (
        sb.table("posts")
        .select("id", count="exact")
        .eq("account_id", acct_id)
        .gte("first_seen_at", start.isoformat())
        .lte("first_seen_at", end.isoformat())
    )


def _stories(sb, acct_id: str, start: datetime, end: datetime):
    return (
        sb.table("stories")
        .select("id", count="exact")
        .eq("account_id", acct_id)
        .gte("first_seen_at", start.isoformat())
        .lte("first_seen_at", end.isoformat())
    )


def _run_counts(sb, job_name: str, handle: str, start: datetime, end: datetime) -> tuple[int, int]:
    rows = (
        sb.table("run_history")
        .select("items_new")
        .eq("job_name", job_name)
        .eq("account_handle", handle)
        .in_("status", ["success", "partial"])
        .gte("started_at", start.isoformat())
        .lte("started_at", end.isoformat())
        .execute()
        .data or []
    )
    return len(rows), sum(1 for r in rows if r["items_new"] == 0)


def compute_health(interval: str) -> tuple[list[AccountHealth], datetime, datetime]:
    start, end = parse_interval(interval)
    sb = get_supabase()

    accounts = (
        sb.table("accounts")
        .select("id, handle, platform")
        .eq("is_active", True)
        .execute()
        .data or []
    )

    results: list[AccountHealth] = []
    for acct_raw in accounts:
        acct = cast(dict[str, Any], acct_raw)
        acct_id = str(acct["id"])
        handle = str(acct["handle"])
        platform = str(acct["platform"])
        row = AccountHealth(handle=handle, account_id=acct_id, platform=platform)

        # --- posts ---
        row.posts_new = _cnt(_posts(sb, acct_id, start, end))
        row.posts_classified = _cnt(
            _posts(sb, acct_id, start, end).not_.is_("ai_category", "null")
        )
        row.posts_classify_fp = _cnt(
            _posts(sb, acct_id, start, end).not_.is_("ai_category", "null").eq("ai_attempts", 0)
        )
        row.posts_described = _cnt(
            _posts(sb, acct_id, start, end).not_.is_("ai_description", "null")
        )
        row.posts_describe_fp = _cnt(
            _posts(sb, acct_id, start, end).not_.is_("ai_description", "null").eq("ai_description_attempts", 0)
        )
        row.posts_describe_oai = _cnt(
            _posts(sb, acct_id, start, end).not_.is_("ai_description", "null").eq("ai_provider", "openai")
        )
        row.post_runs_total, row.post_runs_empty = _run_counts(
            sb, "ingest_posts", handle, start, end
        )

        # --- stories ---
        row.stories_new = _cnt(_stories(sb, acct_id, start, end))
        row.stories_classified = _cnt(
            _stories(sb, acct_id, start, end).not_.is_("ai_category", "null")
        )
        row.stories_classify_fp = _cnt(
            _stories(sb, acct_id, start, end).not_.is_("ai_category", "null").eq("ai_attempts", 0)
        )
        row.stories_described = _cnt(
            _stories(sb, acct_id, start, end).not_.is_("ai_description", "null")
        )
        row.stories_describe_fp = _cnt(
            _stories(sb, acct_id, start, end).not_.is_("ai_description", "null").eq("ai_description_attempts", 0)
        )
        row.story_runs_total, row.story_runs_empty = _run_counts(
            sb, "ingest_stories", handle, start, end
        )

        results.append(row)
        log.debug("health.account_done", handle=handle)

    results.sort(key=lambda r: r.handle)
    return results, start, end


def _pct(num: int, denom: int) -> str:
    if denom == 0:
        return "—"
    return f"{num / denom * 100:.0f}%"


def format_report(rows: list[AccountHealth], interval: str, start: datetime, end: datetime) -> str:
    date_fmt = "%Y-%m-%d"
    lines: list[str] = [
        f"## Data Health — {interval} ({start.strftime(date_fmt)} to {end.strftime(date_fmt)})",
        "",
        "### Posts",
        "| Account | New | Classified | Classified 1st try | Described | Described 1st try | Gemini fallback | Empty runs |",
        "|---------|-----|------------|--------------------|-----------|-------------------|-----------------|------------|",
    ]
    handles = [r.handle for r in rows]
    _needs_platform = {h for h in handles if handles.count(h) > 1}

    def _label(r: AccountHealth) -> str:
        if r.handle in _needs_platform:
            return f"@{r.handle} ({r.platform})"
        return f"@{r.handle}"

    for r in rows:
        lines.append(
            f"| {_label(r)} | {r.posts_new}"
            f" | {_pct(r.posts_classified, r.posts_new)}"
            f" | {_pct(r.posts_classify_fp, r.posts_new)}"
            f" | {_pct(r.posts_described, r.posts_classified)}"
            f" | {_pct(r.posts_describe_fp, r.posts_classified)}"
            f" | {_pct(r.posts_describe_oai, r.posts_described)}"
            f" | {r.post_runs_empty}/{r.post_runs_total} |"
        )

    lines += [
        "",
        "### Stories",
        "| Account | New | Classified | Classified 1st try | Described | Described 1st try | Empty runs |",
        "|---------|-----|------------|--------------------|-----------|-------------------|------------|",
    ]
    for r in rows:
        lines.append(
            f"| {_label(r)} | {r.stories_new}"
            f" | {_pct(r.stories_classified, r.stories_new)}"
            f" | {_pct(r.stories_classify_fp, r.stories_new)}"
            f" | {_pct(r.stories_described, r.stories_classified)}"
            f" | {_pct(r.stories_describe_fp, r.stories_classified)}"
            f" | {r.story_runs_empty}/{r.story_runs_total} |"
        )

    return "\n".join(lines) + "\n"
