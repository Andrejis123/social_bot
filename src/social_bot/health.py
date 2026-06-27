"""
Data health reporting: per-account scraping volume and AI pass rates.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from supabase import Client

from .db.client import get_supabase
from .logging import get_logger

log = get_logger(__name__)

_INTERVAL_DAYS = {"7d": 7, "30d": 30, "90d": 90}


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
    if days := _INTERVAL_DAYS.get(token):
        return now - timedelta(days=days), now
    raise ValueError(f"Unknown interval {token!r}. Use: yesterday, 7d, 30d, 90d")


def _fetch_content(
    sb: Client, table: str, acct_id: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    result = (
        sb.table(table)
        .select("ai_category, ai_attempts, ai_description, ai_description_attempts, ai_provider")
        .eq("account_id", acct_id)
        .gte("first_seen_at", start.isoformat())
        .lte("first_seen_at", end.isoformat())
        .execute()
    )
    return cast(list[dict[str, Any]], result.data or [])


def _run_counts(
    sb: Client, job_name: str, handle: str, start: datetime, end: datetime
) -> tuple[int, int]:
    rows = cast(
        list[dict[str, Any]],
        sb.table("run_history")
        .select("items_new")
        .eq("job_name", job_name)
        .eq("account_handle", handle)
        .in_("status", ["success", "partial"])
        .gte("started_at", start.isoformat())
        .lte("started_at", end.isoformat())
        .execute()
        .data or [],
    )
    return len(rows), sum(1 for r in rows if r["items_new"] == 0)


def compute_health(interval: str) -> tuple[list[AccountHealth], datetime, datetime]:
    start, end = parse_interval(interval)
    sb = get_supabase()

    accounts = cast(
        list[dict[str, Any]],
        sb.table("accounts").select("id, handle, platform").eq("is_active", True).execute().data or [],
    )

    results: list[AccountHealth] = []
    for acct in accounts:
        acct_id = str(acct["id"])
        handle = str(acct["handle"])
        platform = str(acct["platform"])
        row = AccountHealth(handle=handle, account_id=acct_id, platform=platform)

        posts = _fetch_content(sb, "posts", acct_id, start, end)
        row.posts_new = len(posts)
        row.posts_classified = sum(1 for p in posts if p.get("ai_category"))
        row.posts_classify_fp = sum(1 for p in posts if p.get("ai_category") and (p.get("ai_attempts") or 0) == 0)
        row.posts_described = sum(1 for p in posts if p.get("ai_description"))
        row.posts_describe_fp = sum(1 for p in posts if p.get("ai_description") and (p.get("ai_description_attempts") or 0) == 0)
        row.posts_describe_oai = sum(1 for p in posts if p.get("ai_description") and p.get("ai_provider") == "openai")
        row.post_runs_total, row.post_runs_empty = _run_counts(sb, "ingest_posts", handle, start, end)

        stories = _fetch_content(sb, "stories", acct_id, start, end)
        row.stories_new = len(stories)
        row.stories_classified = sum(1 for s in stories if s.get("ai_category"))
        row.stories_classify_fp = sum(1 for s in stories if s.get("ai_category") and (s.get("ai_attempts") or 0) == 0)
        row.stories_described = sum(1 for s in stories if s.get("ai_description"))
        row.stories_describe_fp = sum(1 for s in stories if s.get("ai_description") and (s.get("ai_description_attempts") or 0) == 0)
        row.story_runs_total, row.story_runs_empty = _run_counts(sb, "ingest_stories", handle, start, end)

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
    handle_counts = Counter(r.handle for r in rows)
    _needs_platform = {h for h, c in handle_counts.items() if c > 1}

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
