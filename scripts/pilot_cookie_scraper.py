"""
One-off pilot: test get-leads/all-in-one-instagram-scraper with our session cookies.

NOT part of the pipeline. Delete or move to /tests once we decide whether to wire it in.

Usage:
    uv run python -m scripts.pilot_cookie_scraper
"""

from __future__ import annotations

import json
import os
import sys

from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["APIFY_TOKEN"]
COOKIES = os.environ["INSTAGRAM_COOKIES"]

PROFILES = ["pulzeczech"]
COOKIE_COUNTRY = "SK"

client = ApifyClient(TOKEN)

actor_input = {
    "scrapeMode": "instagram-profile-scraper",
    "profiles": PROFILES,
    "maxPostsPerProfile": 10,
    "loginCookies": COOKIES,
    "cookieCountry": COOKIE_COUNTRY,
    "proxyTier": "none",
}

print(f"Calling get-leads/all-in-one-instagram-scraper for {PROFILES} (cookieCountry={COOKIE_COUNTRY})...")
run = client.actor("get-leads/all-in-one-instagram-scraper").call(run_input=actor_input)

if not run:
    print("ERROR: no run returned", file=sys.stderr)
    sys.exit(1)

print(f"\nRun ID: {run['id']}")
print(f"Status: {run['status']}")
print(f"Started: {run.get('startedAt')}")
print(f"Finished: {run.get('finishedAt')}")

items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
print(f"\nDataset items: {len(items)}")

profile_items = []
report_items = []
error_items = []
for item in items:
    rt = item.get("resultType", "profile")
    if rt == "input_validation_error":
        error_items.append(item)
    elif rt in ("quality_report", "bandwidth_report"):
        report_items.append(item)
    else:
        profile_items.append(item)

if error_items:
    print("\n=== INPUT VALIDATION ERRORS ===")
    for e in error_items:
        print(json.dumps(e, indent=2, default=str)[:2000])

print("\n=== PROFILE RESULTS ===")
for p in profile_items:
    username = p.get("username", "?")
    followers = p.get("followersCount", p.get("followers", "?"))
    posts = p.get("latestPosts", []) or p.get("posts", [])
    print(f"\n@{username}: {len(posts)} posts, {followers} followers")
    print(f"  Full name: {p.get('fullName', '?')}")
    print(f"  Private: {p.get('isPrivate', '?')}")
    print(f"  Verified: {p.get('isVerified', '?')}")
    print(f"  Posts count (total on profile): {p.get('postsCount', p.get('mediaCount', '?'))}")
    for post in posts[:5]:
        shortcode = post.get("shortcode", "?")
        caption = (post.get("caption") or "")[:80].replace("\n", " ")
        likes = post.get("likesCount", post.get("likes", "?"))
        comments = post.get("commentsCount", post.get("comments", "?"))
        post_type = post.get("type") or post.get("postType") or "?"
        print(f"    - {shortcode} ({post_type}, ❤{likes} 💬{comments}): {caption}")

print("\n=== REPORTS ===")
for r in report_items:
    rt = r.get("resultType")
    print(f"\n--- {rt} ---")
    print(json.dumps(r, indent=2, default=str)[:1500])

print("\n=== RAW FIRST ITEM (for schema discovery) ===")
if profile_items:
    keys = sorted(profile_items[0].keys())
    print(f"Top-level keys ({len(keys)}): {keys}")
    if profile_items[0].get("latestPosts"):
        post_keys = sorted(profile_items[0]["latestPosts"][0].keys())
        print(f"\nPost keys ({len(post_keys)}): {post_keys}")
