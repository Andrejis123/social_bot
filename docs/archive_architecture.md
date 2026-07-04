# Archive & storage architecture

How reports get made, where everything lands, and how media is archived off
Supabase to stay under the free-tier storage cap. Written 2026-06-30.

## The constraint that drives all of this

Supabase free tier caps **file storage (Storage buckets) at 1 GB**. This is NOT
the 8 GB figure (that is Pro *DB disk size*). Media is video-heavy and roughly
**one month of scraping fills the 1 GB bucket**, so media cannot accumulate
indefinitely. Every reported period is archived to Google Drive and its bytes
are then purged from Supabase. Postgres rows are tiny and are NOT the constraint,
so we keep rows and only delete the bytes.

## Reports — when and where

- **When:** monthly cron, 1st of the month 08:00 UTC. Window is report-style
  `30-days-ago .. yesterday` (not a calendar month), matching the
  "25 April - 25 May" convention. Driver: `scripts/run_monthly_reports.py`.
- **What:** one Instagram-only `.pptx` deck per client (`agape`,
  `ecig-monitoring`, `iluminatecz`). Code-driven python-pptx, editable output.
- **Where it lands** (each report, best-effort mirror):
  - **Supabase** `reports` bucket — canonical copy + signed URL.
  - **Google Drive** `Reports New/<client>/` (branded) and the production path.
  - **Telegram** — notification with the report.
- Synthesis artifacts (the LLM output) persist to Supabase
  `synthesis_artifacts` so a re-render can skip the LLM via `--reuse-synthesis`.

## Content bundles (zip archives) — when and where

- **What:** a `.zip` of all scraped media for one client across a period. Layout
  mirrors Supabase storage paths so it is self-describing:
  `<handle>/<platform>/posts/<YYYY>/<MM>/<post_id>/<slide_index>.<ext>` and the
  stories equivalent. Built by `scripts/make_content_bundle.py:build_bundle`.
- **When:** monthly cron, 1st of the month 08:30 UTC (right after the report),
  via `scripts/archive_and_purge.py archive` over the same report window.
- **Where it lands:** Google Drive `<client>/data/`. Filename matches the report
  period label, so a client sees `data` + report side-by-side with consistent
  naming. Re-running overwrites in place (deterministic name) — no duplicates.

## The purge — how media leaves Supabase safely

The one invariant: **purge only tombstones bytes proven to live inside a verified
Drive bundle.** Anything that never made it into an archive survives, always.

Mechanism (`scripts/archive_and_purge.py`, two commands, two cron jobs a week
apart):

1. **`archive <start> <end>`** (1st, 08:30) — **all-or-nothing**:
   - Build the zip, downloading each file from Supabase. A download that fails is
     **retried with backoff** (`Server disconnected` is transient, often caused by
     Supabase throttling near the storage cap).
   - If *any* file is still missing after retries, the bundle is **incomplete**:
     the run **aborts that client** — no zip is uploaded, nothing is stamped. The
     client's media stays in Supabase untouched and the period is retried next
     run. A period is therefore either fully archived or not archived at all,
     never partial.
   - On a complete bundle, upload to Drive, then **verify** by byte size
     (local == remote). A size mismatch aborts before any stamping.
   - **Stamp** `archived_at` + `archive_drive_id` on the `media` / `story_media`
     rows in the bundle, only if `archived_at IS NULL` (idempotent — a re-run
     never moves the timestamp, so the grace clock is stable).

2. **`purge --grace-days 7 --apply`** (8th, ~09:00 — a week later for a recovery
   window):
   - Select rows where `archived_at IS NOT NULL` AND `archived_at < now - 7d`
     AND `storage_path IS NOT NULL`. Only these are eligible.
   - **Tombstone:** remove the object from the Supabase bucket and set
     `storage_path = NULL`. The row stays, carrying `archived_at` +
     `archive_drive_id` as a pointer to the Drive copy.
   - Dry-run by default; `--apply` aborts if the candidate set is empty.

Why a row survives a purge:
- never archived (no verified bundle) -> `archived_at` is NULL -> not selected.
- its period's archive was incomplete -> the whole archive aborted, so nothing
  from that period was stamped -> not selected.
- archived less than 7 days ago -> inside grace -> not selected.
- already tombstoned -> `storage_path` is NULL -> not selected.

## What lives where, after a purge

| Layer | Holds | After purge of an old period |
|-------|-------|------------------------------|
| Supabase **DB rows** | posts, stories, media, story_media (metadata) | kept; `storage_path` NULLed, `archived_at`/`archive_drive_id` set |
| Supabase **Storage bucket** | the media bytes | **removed** for purged periods; recent (within retention) kept |
| Google **Drive `<client>/data/`** | the content-bundle zips | the durable media archive |
| Google **Drive Live View** | last ~30 days mirrored for client browsing | pruned at 30 days by the sync job |

**Consequence to remember:** once a period is purged, its media bytes live ONLY
in the Drive bundle. Re-rendering that old report will not have its images
(reports pull from Supabase Storage). This is by design, not a bug — old reports
are already delivered. To re-render an old period, restore its bytes from the
Drive zip first.

## Drive Live View vs content bundles — not the same thing

- **Live View** (`scripts/sync_drive.py`): a browsable mirror of the *last ~30
  days* of media, organised for the client to scroll. Pruned at 30 days. This is
  a convenience view, not the archive.
- **Content bundle** (`<client>/data/*.zip`): the *permanent* archive of a
  reported period. This is what the purge relies on.

## Current operating mode (2026-06-30) — manual, not cron

Scraping is being **wound down** after the first end-to-end report run. While the
pipeline is mothballed, archive + purge run **manually as one-shots**, not on
cron: do one full `archive` of the remaining periods, verify the zips in Drive,
then `purge` Supabase down to near-empty (Drive becomes cold storage). The cron
schedule below is the **target design for when a paying client is live** — wire
it (with report-success gating) then, not now. Report-success gating (a zip only
after that client's report succeeds) is also deferred to that point; for the
one-shot wind-down the human running it is the gate.

## Cron summary (UTC) — target design, not yet wired

```
# monthly, 1st
08:00  run_monthly_reports            (report -> Supabase + Drive + Telegram)
08:30  archive_and_purge archive      (bundle period -> Drive, stamp rows)
# monthly, 8th
09:00  archive_and_purge purge --apply (tombstone archived+grace-expired bytes)
# nightly, after story describes
~23:40 sync_drive ecig-monitoring     (Live View mirror + 30d prune)
~23:50 sync_drive iluminatecz
~00:20 sync_drive agape
```

## One-off / maintenance scripts

- `scripts/_cleanup_stale_junk.py` — supervised raw-delete of pre-project /
  dropped-platform media (no Drive copy). Used 2026-06-30 for pulzecz 2022-23,
  agape 2025 backfill, agapeslovensko FB residual. Bypasses the archive invariant
  on purpose, for confirmed junk only.
- `scripts/cleanup_drive_orphans.py` — deletes Live-tree Drive files with no
  ledger row (after a row purge normal prune can't reach them).
