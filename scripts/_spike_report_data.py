"""
One-shot spike: surface report-relevant data quality for 2026-04-25..2026-05-25.

- Post counts per (account, ai_category)
- Story counts per (account, ai_category)
- 10 sample ai_descriptions across categories
- Flag accounts/categories with zero rows
"""

from __future__ import annotations

import random
from collections import defaultdict

from social_bot.db.client import get_supabase

WINDOW_START = "2026-04-25T00:00:00+00:00"
WINDOW_END = "2026-05-25T23:59:59+00:00"
ACCOUNTS = [
    "ploom.cz", "iqos_cz", "pulzeczech",
    "agapeslovensko", "agape_bratislava",
]


def fetch_account_ids() -> dict[str, str]:
    sb = get_supabase()
    res = sb.table("accounts").select("id, handle").in_("handle", ACCOUNTS).execute()
    return {r["handle"]: r["id"] for r in (res.data or [])}


def counts_by_category(table: str, account_ids: dict[str, str]) -> dict[str, dict[str, int]]:
    sb = get_supabase()
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for handle, aid in account_ids.items():
        res = (
            sb.table(table)
            .select("ai_category, posted_at")
            .eq("account_id", aid)
            .gte("posted_at", WINDOW_START)
            .lte("posted_at", WINDOW_END)
            .execute()
        )
        for row in (res.data or []):
            cat = row.get("ai_category") or "(uncategorised)"
            out[handle][cat] += 1
    return out


def sample_descriptions(account_ids: dict[str, str], n: int = 10) -> list[dict]:
    sb = get_supabase()
    rows: list[dict] = []
    for handle, aid in account_ids.items():
        res = (
            sb.table("posts")
            .select("ai_category, ai_description, caption, posted_at")
            .eq("account_id", aid)
            .gte("posted_at", WINDOW_START)
            .lte("posted_at", WINDOW_END)
            .not_.is_("ai_description", "null")
            .execute()
        )
        for r in (res.data or []):
            r["_handle"] = handle
            rows.append(r)
    random.seed(42)
    random.shuffle(rows)
    # try to span categories: one per (handle, category) until we hit n
    seen: set[tuple[str, str]] = set()
    picked: list[dict] = []
    for r in rows:
        key = (r["_handle"], r.get("ai_category") or "(uncat)")
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)
        if len(picked) >= n:
            break
    # fill remaining slots with any leftover
    if len(picked) < n:
        for r in rows:
            if r in picked:
                continue
            picked.append(r)
            if len(picked) >= n:
                break
    return picked


def main() -> None:
    account_ids = fetch_account_ids()
    print(f"\n# Accounts found ({len(account_ids)}):")
    for h, aid in account_ids.items():
        print(f"  {h}: {aid}")

    print("\n# Posts per (account, category)")
    post_counts = counts_by_category("posts", account_ids)
    for handle in ACCOUNTS:
        if handle not in account_ids:
            print(f"  {handle}: ACCOUNT NOT FOUND")
            continue
        cats = post_counts.get(handle, {})
        total = sum(cats.values())
        line = ", ".join(f"{c}={n}" for c, n in sorted(cats.items())) or "(none)"
        print(f"  {handle} [total={total}]: {line}")

    print("\n# Stories per (account, category)")
    story_counts = counts_by_category("stories", account_ids)
    for handle in ACCOUNTS:
        if handle not in account_ids:
            continue
        cats = story_counts.get(handle, {})
        total = sum(cats.values())
        line = ", ".join(f"{c}={n}" for c, n in sorted(cats.items())) or "(none)"
        print(f"  {handle} [total={total}]: {line}")

    print("\n# Sample ai_descriptions (up to 10, max-coverage across handle/category)")
    samples = sample_descriptions(account_ids, n=10)
    for i, r in enumerate(samples, 1):
        cap = (r.get("caption") or "")[:100].replace("\n", " ")
        desc = (r.get("ai_description") or "").replace("\n", " ")
        print(f"\n--- Sample {i} — @{r['_handle']} · {r.get('ai_category')} · {r.get('posted_at', '')[:10]}")
        print(f"  caption: {cap}")
        print(f"  ai_desc: {desc}")


if __name__ == "__main__":
    main()
