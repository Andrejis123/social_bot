# Plan: Google Drive "Live View" of scraped content (client-facing)

## Context

Clients currently only see a monthly report. There's no way for them to confirm
we're actually scraping, nor to watch competitor/own activity day to day. The
goal: mirror newly scraped media into a **per-client Google Drive folder shared
by link**, so a client opens one link and browses
`@account → Stories/Posts → date`. Two payoffs: (1) **trust** (visible proof of
daily scraping), (2) **competitive intel** (all monitored accounts/platforms in
one browsable place).

This reuses the existing scrape→Supabase-Storage pipeline; nothing about scrape
or describe changes. A new post-describe step downloads already-stored media and
mirrors it to Drive, with a 30-day rolling retention prune.

### Decisions locked with Andy
- **Layout:** account → content-type → date. `@<handle>/Stories/<YYYY-MM-DD>/…`
  and `@<handle>/Posts/<YYYY-MM-DD>_<post_id>/…`. Separate folder per account
  (not grouped); ISO dates so they sort chronologically.
- **Retention:** all media incl. video; auto-delete Drive files older than **30
  days**. The 30-day window also bounds what gets synced (so pruned items don't
  re-sync).
- **Fidelity (quota control):** the live view is a low-fidelity "proof + glance"
  surface; the client still gets the full-resolution raw zip at interval end
  (`make_content_bundle`). So everything is downsized before upload:
  - **Images** → JPEG quality ~82, downscaled to ~1080px long edge (reuse the
    `_compress_image` pattern). Collapses to tens of KB.
  - **Video (stories + reels)** → ffmpeg transcode to ~480p, low bitrate
    (~10x smaller, still playable). Requires adding ffmpeg to the image.
  - Reel cover stills (`slide_index=99`) are **skipped** in the live view since
    the transcoded reel video already represents the post.
- **Sharing:** "anyone with the link → viewer" on the per-client folder, set
  once (client needs no Google account). *Expected to work under the current
  `drive.file` scope, but verified first — see Step 0.*
- **Captions:** media only for v1 (post folders named by date + post id; no
  sidecar text yet).

## Critical constraint: keep reports private

Report drafts live under root `SMM - Reports/<client>/reports/draft/`. The live
view is shared world-readable, so it MUST live under a **separate root**. Add a
new setting `GOOGLE_DRIVE_LIVE_ROOT_FOLDER` (default `"SMM - Live"`) and share
only `SMM - Live/<client>/`. Never set an "anyone" permission anywhere under
`SMM - Reports`.

## Changes

### Step 0 (do FIRST — de-risks the whole approach): verify link-sharing
Before any build, run a ~10-min spike: with the *existing* Drive service, create
a throwaway folder, call `permissions().create({type:"anyone", role:"reader"})`,
then open its `webViewLink` in a logged-out/incognito browser.
- Confirms `drive.file` scope permits anyone-reader on app-created files.
- Confirms Andy's Google account/domain policy doesn't disable "anyone with
  link" sharing (a Workspace policy can block this even when scope is fine).
If it fails, the fix is costly (re-mint refresh token under the broader `drive`
scope; the OAuth app's "In production" status is fragile per `drive.py` docstring
and may force re-consent). So: prove this works before writing the migration.

### 1. Settings — `src/social_bot/config.py`
Add `google_drive_live_root_folder: str = Field("SMM - Live",
alias="GOOGLE_DRIVE_LIVE_ROOT_FOLDER")` next to the existing
`google_drive_root_folder` (line ~72).

### 1b. ffmpeg in the image — `docker/Dockerfile`
Append `ffmpeg` to the existing apt line (~line 12:
`apt-get install -y --no-install-recommends ca-certificates curl ffmpeg`).
Adds ~a few hundred MB to the image; rebuild happens via the normal `just deploy`
flow. Confirm `ffmpeg -version` runs inside the built image during deploy-check.

### 2. Migration — `migrations/0005_drive_sync.sql`
Add a sync ledger so re-runs don't duplicate and retention knows what to delete:
```sql
ALTER TABLE media       ADD COLUMN drive_file_id text, ADD COLUMN drive_synced_at timestamptz;
ALTER TABLE story_media ADD COLUMN drive_file_id text, ADD COLUMN drive_synced_at timestamptz;
CREATE INDEX media_drive_synced_idx       ON media (drive_synced_at);
CREATE INDEX story_media_drive_synced_idx ON story_media (drive_synced_at);
```
(Apply via the same path used for prior migrations — confirm in README/justfile.)

### 3. Drive helpers — `src/social_bot/drive.py`
Reuse `get_or_create_folder`, `_build_service`, the folder cache. Add:
- `upload_bytes(*, data: bytes, name: str, drive_folder_path: str, mime_type: str,
  overwrite: bool = False) -> dict` — in-memory upload via
  `MediaIoBaseUpload(io.BytesIO(data), …)`, mirroring `upload_file`'s
  create/update logic. Avoids temp files. `overwrite=False` skips the
  find-existing call (the DB ledger already guards re-sync).
- `share_folder_anyone(folder_path: str) -> str` — idempotently ensure an
  `{type:"anyone", role:"reader"}` permission via `service.permissions().create`,
  then return the folder's `webViewLink` (`files().get(fields="webViewLink")`).
  (Permission-on-app-created-file behavior proven in Step 0.)
- `delete_file(file_id: str) -> None` — `service.files().delete()` for retention,
  tolerating 404.

### 4. New queries — `src/social_bot/db/queries.py`
- Extend `list_posts_in_period` select to also return `post_type` (for naming).
- `list_unsynced_post_media(account_ids, since) -> rows` — media joined to posts
  with `posted_at >= since` AND `drive_synced_at IS NULL`; return
  `post_id, platform_post_id, posted_at, slide_index, media_type, storage_path,
  media_id`. Story equivalent `list_unsynced_story_media(account_ids, since)`.
- `mark_media_synced(media_id, drive_file_id)` /
  `mark_story_media_synced(story_media_id, drive_file_id)`.
- `list_expired_drive_media(cutoff)` / story equivalent — rows with
  `drive_synced_at IS NOT NULL AND posted_at < cutoff`, returning
  `media_id, drive_file_id`, for the prune pass to delete + clear.
- `clear_media_drive(media_id)` / story equivalent — null both drive columns.

### 4b. Media optimization — `src/social_bot/media_optimize.py`
New small module (keeps PIL/ffmpeg concerns out of the pipeline):
- `compress_image(data: bytes, *, max_long_edge=1080, quality=82) -> bytes` —
  PIL `thumbnail()` + JPEG `quality`, `optimize=True`, RGBA→white flatten.
  Mirrors `reports/layouts.py:_compress_image` but takes/returns bytes and sizes
  by a pixel long-edge instead of EMU box dims. (Optional: refactor the shared
  encode tail of `_compress_image` into this module and have layouts call it.)
- `transcode_video(data: bytes) -> bytes` — write to temp, run ffmpeg
  `-vf scale=-2:480 -c:v libx264 -crf 30 -preset veryfast -c:a aac -b:a 64k
  -movflags +faststart`, read result back. Raise on non-zero exit; caller logs
  and skips that one file rather than failing the run.

### 5. Pipeline module — `src/social_bot/pipeline/sync_drive.py`
`sync_client_to_drive(client_slug, window_days=30)`:
1. Resolve `client_id` (`get_client_id_by_slug`) and accounts
   (`list_accounts_for_client`).
2. `since = now - window_days`. Ensure `SMM - Live/<client>/` exists and is
   shared (`share_folder_anyone`); log the link.
3. For each account, for unsynced post media and story media within the window
   (skip `slide_index=99` reel covers):
   - `data, mime = download_from_storage(storage_path)` (reuse
     `src/social_bot/storage/media.py:download_from_storage`).
   - **Optimize before upload** (`media_optimize`): if `media_type=="image"` →
     `compress_image(data)` and force `.jpg` + image/jpeg; if `"video"` →
     `transcode_video(data)`, keep `.mp4`. On transcode error, log + skip that
     file (don't mark synced; it retries next run).
   - Build Drive folder path:
     - posts: `SMM - Live/<client>/@<handle>/Posts/<YYYY-MM-DD>_<platform_post_id>`
     - stories: `SMM - Live/<client>/@<handle>/Stories/<YYYY-MM-DD>`
   - File name: posts `<slide_index>.<ext>`; stories `<story_id>.<ext>` (ext from
     mime/media_type).
   - `upload_bytes(...)` → `mark_*_synced(media_id, file_id)`.
4. **Prune:** `cutoff = now - window_days`; for `list_expired_drive_media` rows:
   `delete_file(drive_file_id)` then `clear_media_drive(media_id)`.
5. Wrap in `RunContext` for run_history bookkeeping, but **suppress the Telegram
   notification** for this job. Sync runs nightly (stories) + weekly (posts) per
   client; a ping every run is spam and conflicts with `feedback.md`'s minimal-
   notification convention. Default to silent (run_history only); surface a
   Telegram message only on failure or on the quota-warning below. Confirm how
   RunContext gates notifications and pass the silent flag (or a no-op notifier).

### 6. CLI — `scripts/sync_drive.py`
Typer entry `python -m scripts.sync_drive --client <slug> [--window-days 30]`,
mirroring `scripts/describe_posts.py`. Calls `sync_client_to_drive`.

### 7. Justfile + cron
- Recipes: `sync-drive <client>` (manual) and `cron-sync-drive <client>`.
- VPS crontab: add `cron-sync-drive <client>` after each client's
  `cron-describe` (posts, Mondays) and after `cron-describe-stories` (nightly),
  so the live view updates right after descriptions land. (Crontab edited on the
  VPS per CLAUDE.md; document the new lines.)

## Reused, not rebuilt
- `storage/media.py:download_from_storage` — bytes + mime out of Supabase.
- `db/queries.py` batch helpers — `list_accounts_for_client`,
  `get_client_id_by_slug`, period/media listers (extended above).
- `drive.py` — folder create/cache, auth, upload pattern.
- `RunContext` — run_history + Telegram bookkeeping (same as describe jobs).

## Quota note
Personal My Drive (15 GB free) is the constraint. Compression (images ~82,
video ~480p) plus the 30-day prune should keep this comfortably bounded — image
media shrinks to tens of KB and 480p video is ~10x smaller than source. Still
log a one-line storage check (`service.about().get(fields="storageQuota")`) each
run and warn via Telegram above ~80%, so a surprise (e.g. a heavy-video month)
surfaces before uploads start failing.

## Verification (real data, per CLAUDE.md)
1. Apply migration 0005; confirm columns exist.
2. Confirm `ffmpeg -version` works locally (and inside the image at deploy-check).
3. Dry single account: `just sync-drive ecig-monitoring` against a small window.
   - Confirm `SMM - Live/ecig-monitoring/@pulzeczech/Stories/<date>/…` and
     `…/Posts/<date>_<id>/<slide>.jpg` appear in Drive with correct media.
   - Spot-check sizes: images are JPEGs in the tens of KB; a story video plays
     and is ~480p / much smaller than the Supabase original.
   - Confirm `media.drive_synced_at`/`drive_file_id` populated.
4. Re-run immediately: verify **no duplicate** uploads (ledger guard works).
5. Open `share_folder_anyone` link in a logged-out browser → folder is viewable;
   confirm `SMM - Reports` is NOT publicly viewable.
6. Retention: temporarily set a tiny window (e.g. 0 days) on a throwaway run and
   confirm the prune deletes the Drive files and clears the columns.
7. `just check` green (add unit tests for path-building, ext-from-mime, and
   image-compress size reduction; mock Drive/Storage/ffmpeg). Then `just deploy`
   + `just deploy-check` (incl. ffmpeg present in the image).

## Open follow-ups (not in v1)
- Per-day index file with captions + AI descriptions + permalinks (the
  "captions" enhancement) — strong intel value, deferred.
- Quota headroom / possible Google One upgrade if 30d all-media exceeds 15 GB.
- **GDPR:** "anyone with link" makes scraped content (incl. competitors' personal
  data) publicly forwardable. Competitor IG content is already public, but this
  sharing decision should be on the radar of the existing Notion task "Run GDPR
  compliance check on social-bot before production." Add it there before go-live.
