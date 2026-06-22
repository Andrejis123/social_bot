"""
Validate the synthesis module end-to-end on real data.

For each test cell: run synthesize_category(), show Pass 0 prose,
all cluster items (title + narrative + best_post_id), and audit
narrative length + em-dash compliance + reel-preference.

Second pass exercises the cache (should be silent, no LLM calls).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime

from social_bot.reports.data import build_period, load_report_data
from social_bot.reports.synthesis import synthesize_category

CLIENT = "ecig-monitoring"
START = datetime(2026, 4, 25, 0, 0, 0, tzinfo=UTC)
END = datetime(2026, 5, 25, 23, 59, 59, tzinfo=UTC)

CELLS = [
    ("iqos_cz", "Events", "IQOS"),
    ("ploom.cz", "Events", "Ploom"),
]


def audit(item, posts_by_id) -> list[str]:
    flags = []
    n_words = len(item.narrative.split())
    if n_words > 18:
        flags.append(f"narrative_too_long({n_words}w)")
    if "—" in item.narrative or " - " in item.narrative or " -- " in item.narrative:
        flags.append("dash_in_narrative")
    if "—" in item.title or " - " in item.title or " -- " in item.title:
        flags.append("dash_in_title")
    return flags


def main() -> None:
    period = build_period(START, END)
    rd = load_report_data(CLIENT, period)
    posts_by_account = {a.handle: a.posts_by_category for a in rd.accounts}

    for run_label in ("FRESH", "CACHED"):
        t0 = time.time()
        print(f"\n\n#############  RUN: {run_label}  #############")
        for handle, category, brand in CELLS:
            posts = posts_by_account.get(handle, {}).get(category, [])
            posts_by_id = {p.id: p for p in posts}
            print(f"\n{'=' * 78}")
            print(f"# @{handle} · {category} ({brand}) · {len(posts)} posts")
            print('=' * 78)
            if not posts:
                print("  (empty)")
                continue

            cs = synthesize_category(
                client_slug=CLIENT,
                period_label=period.label,
                brand_label=brand,
                category=category,
                posts=posts,
            )

            print(f"\n[Pass 0] Category narrative ({len(cs.category_narrative.split())} words):")
            print(f"  {cs.category_narrative}")

            print(f"\n[Pass 1+2] Items ({len(cs.items)}):")
            for it in cs.items:
                flags = audit(it, posts_by_id)
                tag = f"  ⚠ {','.join(flags)}" if flags else ""
                bp = posts_by_id.get(it.best_post_id)
                bp_repr = (f"{it.best_post_id[:8]} [{bp.post_type}] "
                           f"likes={bp.like_count}" if bp else f"{it.best_post_id} (missing)")
                n = len(it.narrative.split())
                print(f"  • {it.title}")
                print(f"      narr ({n}w): {it.narrative}{tag}")
                print(f"      best: {bp_repr}")

        print(f"\n[{run_label}] elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
