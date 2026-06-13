"""
One-shot spike: load_report_data() against ecig-monitoring for 2026-04-25..2026-05-25.

Prints what `data.py` returns so we can sanity-check before wiring synthesis:
- Account list (ordering)
- Per-account totals (posts / reels / stories / likes / comments)
- Category buckets with sizes
- Hero-image path resolved per post (or None)
- Intro previews (which category + image was picked)
- Self-healing of reel covers (count of media rows inserted this run)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from social_bot.reports.data import build_period, load_report_data

CLIENT = "ecig-monitoring"
START = datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 5, 25, 23, 59, 59, tzinfo=timezone.utc)


def main() -> None:
    period = build_period(START, END)
    print(f"# Period: {period.label}  ({period.start.date()} to {period.end.date()})\n")

    rd = load_report_data(CLIENT, period, cache_dir=Path("/tmp/report_images"))

    print(f"Client: {rd.client_name} ({rd.client_slug})")
    print(f"Accounts: {[a.handle for a in rd.accounts]}")
    print(f"Grand total posts (incl reels): {rd.grand_total_posts}")

    for a in rd.accounts:
        print(f"\n{'=' * 76}\n# @{a.handle}\n{'=' * 76}")
        print(f"Totals: posts={a.total_posts}  reels={a.total_reels}  "
              f"stories={a.total_stories}  likes={a.total_likes}  "
              f"comments={a.total_comments}")

        print(f"\n  Posts by category (sorted by count desc):")
        for cat, plist in a.posts_by_category.items():
            with_img = sum(1 for p in plist if p.hero_image_path)
            print(f"    {cat}: {len(plist)} posts ({with_img} with image)")

        if a.stories_by_category:
            print(f"\n  Stories by category:")
            for cat, slist in a.stories_by_category.items():
                with_img = sum(1 for s in slist if s.hero_image_path)
                print(f"    {cat}: {len(slist)} stories ({with_img} with image)")

        print(f"\n  Intro previews (max 4): {len(a.intro_previews)}")
        for prev in a.intro_previews:
            exists = "✓" if prev.image_path.exists() else "✗"
            print(f"    {exists} {prev.name} ({prev.post_count} posts) → {prev.image_path.name}")

        # Spot a few posts with full details so we can verify integrity
        first_cat = next(iter(a.posts_by_category), None)
        if first_cat:
            print(f"\n  Sample posts in '{first_cat}' (first 3):")
            for p in a.posts_by_category[first_cat][:3]:
                cap = (p.caption or "")[:60].replace("\n", " ")
                desc = (p.ai_description or "")[:80].replace("\n", " ")
                hero = p.hero_image_path.name if p.hero_image_path else "(no image)"
                print(f"    {p.posted_at.date()} [{p.post_type}] likes={p.like_count} "
                      f"comments={p.comment_count} hero={hero}")
                if cap:
                    print(f"      caption: {cap}")
                if desc:
                    print(f"      ai_desc: {desc}")


if __name__ == "__main__":
    main()
