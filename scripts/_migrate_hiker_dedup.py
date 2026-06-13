"""Migrate shortcode-keyed posts to pk-keyed.

For each row where `platform_post_id` is a shortcode (came from old hiker
normalizer), look at `raw_payload->pk`:
  - if a row with that pk already exists for the same account → DELETE the
    shortcode row (older pk row keeps its AI work; cascades drop the
    shortcode row's metrics/media which the next scrape will refresh).
  - otherwise → UPDATE the shortcode row's platform_post_id to the pk.

Set DRY_RUN=1 to count without writing.
"""
import os
import sys
from social_bot.db.client import get_supabase

DRY = os.environ.get("DRY_RUN") == "1"
sb = get_supabase()

rows = sb.table("posts").select(
    "id,account_id,platform_post_id,raw_payload,first_seen_at,ai_category"
).execute().data

shortcode_rows = []
for r in rows:
    pid = r["platform_post_id"] or ""
    if not pid.isdigit():
        shortcode_rows.append(r)

print(f"Mode: {'DRY-RUN' if DRY else 'APPLY'}")
print(f"Found {len(shortcode_rows)} shortcode rows to process\n")

# Build (account_id, pk) → numeric-row index
numeric_by_acc_pk = {}
for r in rows:
    pid = r["platform_post_id"] or ""
    if pid.isdigit():
        numeric_by_acc_pk[(r["account_id"], pid)] = r

deletes = []
updates = []
skipped_nopk = []

for r in shortcode_rows:
    raw = r.get("raw_payload") or {}
    pk = raw.get("pk")
    if not pk:
        skipped_nopk.append(r)
        continue
    pk = str(pk)
    key = (r["account_id"], pk)
    if key in numeric_by_acc_pk:
        deletes.append((r, numeric_by_acc_pk[key]))
    else:
        updates.append((r, pk))

print(f"  DELETE (numeric counterpart exists): {len(deletes)}")
print(f"  UPDATE platform_post_id → pk:        {len(updates)}")
print(f"  SKIP (no pk in raw_payload):         {len(skipped_nopk)}")

if skipped_nopk:
    print("\nSkipped rows:")
    for r in skipped_nopk[:5]:
        print(f"  id={r['id']} platform_post_id={r['platform_post_id']}")

print("\nSample deletes (shortcode → numeric kept):")
for r, n in deletes[:5]:
    print(f"  {r['platform_post_id']:<20} → keep {n['platform_post_id']} (first_seen={n['first_seen_at'][:10]}, ai={n.get('ai_category')})")

print("\nSample updates:")
for r, pk in updates[:5]:
    print(f"  {r['platform_post_id']:<20} → {pk}")

if DRY:
    print("\nDRY_RUN — nothing written. Re-run without DRY_RUN=1 to apply.")
    sys.exit(0)

print("\nApplying...")
n_del, n_upd = 0, 0
for r, _ in deletes:
    sb.table("posts").delete().eq("id", r["id"]).execute()
    n_del += 1
for r, pk in updates:
    sb.table("posts").update({"platform_post_id": pk}).eq("id", r["id"]).execute()
    n_upd += 1
print(f"Done. deleted={n_del} updated={n_upd}")
