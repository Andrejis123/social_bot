"""
Spike for Path 3 synthesis — Pass 1 (cluster) + Pass 2 (per-cluster narrative + best_post_id).

Validates both prompts end-to-end on two cells:
  - iqos_cz Events    (small: 2 posts in window)
  - ploom.cz Events   (large: 17 posts in window)

Both passes:
  - gemini-2.5-flash, thinking_budget=0
  - Prompts forbid em-dashes (and ` - `, ` -- ` as substitutes)
  - Pass 2 prefers non-reel as best_post_id when a cluster mixes types

Prints prompts + responses so we can judge cluster quality, narrative tone,
and best_post_id picks before integrating into the renderer.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from google import genai
from google.genai import types

from social_bot.config import get_settings
from social_bot.reports.data import build_period, load_report_data

CLIENT = "ecig-monitoring"
START = datetime(2026, 4, 25, 0, 0, 0, tzinfo=UTC)
END = datetime(2026, 5, 25, 23, 59, 59, tzinfo=UTC)

# (handle, category, brand_label)
CELLS = [
    ("iqos_cz", "Events", "IQOS"),
    ("ploom.cz", "Events", "Ploom"),
]


# ─────────────────────────────────────────────────────────────────────
# Pass 1 — cluster
# ─────────────────────────────────────────────────────────────────────

CLUSTER_SYSTEM = """You group social media posts into thematic clusters for a monthly competitor-monitoring report.

A cluster represents ONE distinct campaign, event, partnership, or theme that the brand engaged with during the month. A festival with 10 posts across 3 days is one cluster. An influencer collaboration with 1 post per week is one cluster. A standalone product reminder is its own cluster.

Rules:
- Assign every post to exactly one cluster. Do not drop or duplicate posts.
- Aim for 2-8 clusters per category. Fewer if posts are tightly themed; more if genuinely varied.
- Cluster titles must be specific. Name the event, brand, campaign, or product whenever possible (e.g. "HRADY CZ festival presence", "Adriatique x Seletti at Sensorium Worlds", "Pulze 3.0 launch teasers"). Avoid vague titles like "Various events" or "Promotional posts".
- A single-post cluster is acceptable when the post stands alone thematically.
- Titles must NOT contain em-dashes (—) or use ` - ` / ` -- ` as a separator. Use commas, colons, or parentheses instead.
- Output STRICT JSON only, no commentary, no markdown fences.

Output schema:
{
  "clusters": [
    {"title": "string", "post_ids": ["id1", "id2", ...]}
  ]
}
"""


def build_cluster_user_prompt(brand: str, category: str, posts) -> str:
    lines = [
        f"Brand: {brand}",
        f"Category: {category}",
        f"Posts to cluster ({len(posts)}):",
        "",
    ]
    for p in posts:
        cap = (p.caption or "").strip().replace("\n", " ")[:180]
        desc = (p.ai_description or "").strip().replace("\n", " ")
        date = p.posted_at.date().isoformat()
        lines.append(f"--- id: {p.id}")
        lines.append(f"  date: {date}  type: {p.post_type}")
        if cap:
            lines.append(f"  caption: {cap}")
        if desc:
            lines.append(f"  ai_description: {desc}")
        lines.append("")
    lines.append("Output the JSON now.")
    return "\n".join(lines)


def run_pass1(brand: str, category: str, posts) -> dict:
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    user_prompt = build_cluster_user_prompt(brand, category, posts)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Part.from_text(text=user_prompt)],
        config=types.GenerateContentConfig(
            system_instruction=CLUSTER_SYSTEM,
            temperature=0.2,
            max_output_tokens=1200,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    usage = getattr(response, "usage_metadata", None)
    print(f"  [pass1 usage={usage}]")
    return json.loads(response.text)


# ─────────────────────────────────────────────────────────────────────
# Pass 2 — per-cluster narrative + best_post_id
# ─────────────────────────────────────────────────────────────────────

ITEM_SYSTEM = """You write ONE concise narrative line per cluster for a social-media monitoring slide, and pick the single most representative post.

Style:
- Exactly 1 sentence (max ~25 words). Past tense. Factual, observational tone — not promotional.
- Name people, brands, events, products when the post evidence mentions them.
- Plain English; translate non-English content references inline.
- No hashtags, no emojis, no metrics, no preamble.
- No em-dashes (—) and no ` - ` / ` -- ` as separators. Use commas, colons, or sentence breaks.

Best post pick:
- Identify the single post that best represents the cluster — the one whose image you would use as the hero on a slide.
- When the cluster mixes reel and non-reel posts, prefer a non-reel post: its still image is purpose-composed, while a reel's cover is a video keyframe and often less clear.
- If the cluster has only reels, pick the reel with the most engagement signal in the evidence (or the one whose visual content best matches the narrative).

Output STRICT JSON only:
{"narrative": "string", "best_post_id": "string"}
"""


def build_item_user_prompt(brand: str, category: str, cluster_title: str, posts) -> str:
    lines = [
        f"Brand: {brand}",
        f"Category: {category}",
        f"Cluster: {cluster_title}",
        f"Posts in this cluster ({len(posts)}):",
        "",
    ]
    for p in posts:
        cap = (p.caption or "").strip().replace("\n", " ")[:200]
        desc = (p.ai_description or "").strip().replace("\n", " ")
        date = p.posted_at.date().isoformat()
        lines.append(f"--- id: {p.id}")
        lines.append(f"  date: {date}  type: {p.post_type}  "
                     f"likes: {p.like_count}  comments: {p.comment_count}")
        if cap:
            lines.append(f"  caption: {cap}")
        if desc:
            lines.append(f"  ai_description: {desc}")
        lines.append("")
    lines.append("Output the JSON now.")
    return "\n".join(lines)


def run_pass2(brand: str, category: str, cluster_title: str, posts) -> dict:
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    user_prompt = build_item_user_prompt(brand, category, cluster_title, posts)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Part.from_text(text=user_prompt)],
        config=types.GenerateContentConfig(
            system_instruction=ITEM_SYSTEM,
            temperature=0.3,
            max_output_tokens=300,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    usage = getattr(response, "usage_metadata", None)
    print(f"    [pass2 usage={usage}]")
    return json.loads(response.text)


# ─────────────────────────────────────────────────────────────────────
# Spike orchestrator
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    period = build_period(START, END)
    rd = load_report_data(CLIENT, period)

    posts_by_account = {a.handle: a.posts_by_category for a in rd.accounts}

    for handle, category, brand in CELLS:
        cats = posts_by_account.get(handle, {})
        posts = cats.get(category, [])
        print(f"\n{'=' * 80}")
        print(f"# @{handle} · {category} ({brand}) · {len(posts)} posts")
        print('=' * 80)
        if not posts:
            print("  (no posts — skipping)")
            continue

        # Coverage check
        types_in_set = {p.post_type for p in posts}
        print(f"Post types in this cell: {types_in_set}")
        print("Posts (id snippets):")
        for p in posts:
            print(f"  {p.id[:8]}  {p.posted_at.date()}  {p.post_type:8}  "
                  f"likes={p.like_count:4d}  com={p.comment_count:3d}")

        # ── Pass 1 ──
        print("\n--- PASS 1: cluster ---")
        pass1 = run_pass1(brand, category, posts)
        clusters = pass1.get("clusters", [])
        print(f"  → {len(clusters)} clusters")
        all_ids = [p.id for p in posts]
        seen_ids = []
        for c in clusters:
            print(f"  • {c['title']}  ({len(c['post_ids'])} posts)")
            for pid in c["post_ids"]:
                marker = "✓" if pid in all_ids else "✗ UNKNOWN ID"
                print(f"      {marker} {pid[:8]}")
                seen_ids.append(pid)
        missing = set(all_ids) - set(seen_ids)
        dup = [pid for pid in seen_ids if seen_ids.count(pid) > 1]
        if missing:
            print(f"  ⚠ missing post_ids in clusters: {missing}")
        if dup:
            print(f"  ⚠ duplicate post_ids across clusters: {set(dup)}")

        # ── Pass 2 (per cluster) ──
        print("\n--- PASS 2: per-cluster narrative + best_post_id ---")
        posts_by_id = {p.id: p for p in posts}
        for c in clusters:
            cluster_posts = [posts_by_id[pid] for pid in c["post_ids"] if pid in posts_by_id]
            if not cluster_posts:
                continue
            print(f"\n  Cluster: {c['title']}")
            out = run_pass2(brand, category, c["title"], cluster_posts)
            narrative = out.get("narrative", "")
            best_id = out.get("best_post_id", "")
            best_post = posts_by_id.get(best_id)
            print(f"    narrative: {narrative}")
            if best_post:
                print(f"    best_post: {best_id[:8]}  [{best_post.post_type}]  "
                      f"likes={best_post.like_count}")
                # em-dash audit
                if "—" in narrative or " - " in narrative or " -- " in narrative:
                    print("    ⚠ DASH SEPARATOR DETECTED in narrative")
                # reel preference audit
                non_reels = [p for p in cluster_posts if p.post_type != "reel"]
                if non_reels and best_post.post_type == "reel":
                    print("    ⚠ picked reel as best when non-reels available")
            else:
                print(f"    ⚠ best_post_id {best_id!r} not in cluster")


if __name__ == "__main__":
    main()
