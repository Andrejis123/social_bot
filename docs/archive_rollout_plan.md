# Archive rollout — live progression tracker

Working doc for the multi-part storage/archive/purge rollout (session 2026-06-30
to 2026-07-01). Kept in order so we don't lose the thread across days. Compresses
to a single `project_journal.md` entry once the experiment finishes clean.

Legend: [x] done · [~] in progress · [ ] pending · (VPS) runs on the server.

## Background / decisions

- Free tier caps **file storage at 1 GB**. Real bucket usage ~0.955 GB (dashboard
  1.317 GB is a lagging billing average, not point-in-time).
- **Mothball after this e2e**: stop all scraping; archive/purge run as one-shots,
  recurring cron deferred until a paying client is live.
- **Archive invariant**: purge only tombstones rows proven inside a verified Drive
  bundle (stamped `archived_at`) past a grace window. Tombstone = storage delete +
  NULL `storage_path`; row survives as ledger pointer (`archive_drive_id`).
- **All-or-nothing archive**: any download still failing after retries aborts the
  client (no partial zip, nothing stamped).
- **Root cause of ecig report failure (2026-07-01 08:01)**: unretried Supabase
  read timeout. `download_from_storage` had no retry, so one blip failed the
  client. Fix = read-level retry (also helps describe + Drive sync).

## Phase 1 — engine + cleanup  [x]

- [x] Migration 0006 (archived_at + archive_drive_id) applied to prod.
- [x] `archive_and_purge.py` (archive/purge, dry-run default, 7d grace, size-verify).
- [x] `build_bundle` returns verified written-paths; all-or-nothing in archive cmd.
- [x] Deleted ~112 MB stale junk (pulzecz 2022-23, agape/agapeslovensko 2025, FB).
- [x] `storage_breakdown.py` (+ folded into /data-health).
- [x] Architecture doc `research/archive_architecture.md`.
- [x] Committed `cc12c15`, deployed, deploy-check + in-image smoke passed.
- [x] e2e-verified archive on real iluminatecz (then rolled back).

## Phase 2 — robustness batch (UNCOMMITTED, in this working tree)  [~]

- [x] Read-level retry in `download_from_storage` (4 tries, backoff).
- [x] Telegram `notify_report_failed` wired into run_monthly_reports failure path.
- [x] `purge --client <slug>` scoping (enables per-client grace).
- [x] `restore_from_bundle.py` (+ drive.download_file, media.upload_to_storage,
  queries.restore_media_row/restore_story_media_row) — recovery, dry-run default.
- [ ] `/simplify` + `/security-review` (via /commit-session).
- [ ] Andy runs `/commit-session` → deploy.
- Tests: **165 green** (restore parse + guarded un-tombstone + full
  stamp->tombstone->restore round trip).

## Phase 3 — cron test experiment (AFTER deploy)  [ ]

Timeline (all UTC). iluminatecz already archived+stamped 2026-07-01 18:14
(drive_id 1PQFChv7rqBuZnZJHpjc2BOuEBbRbp5gq).

- [x] Batch deployed (commit `1c18ad8`, deploy-check + import smoke passed).
- [x] (VPS) Wired temporary test crons (marked block in crontab, backup saved):
  - `2 20 1 7 *`  archive `agape iluminatecz` (fires **1 Jul 20:02 UTC**).
  - `30 20 2 7 *` purge `--client agape --grace-days 1 --apply` (**2 Jul 20:30**).
  - `30 20 8 7 *` purge `--client iluminatecz --grace-days 7 --apply` (**8 Jul 20:30**).
- [x] **Today (1 Jul)**: archive cron fired 20:02:29. agape zip in Drive
  (drive_id `1gB1PSZv2S0RXoFmc7zS_Ro6Rx6-aBVuc`, 40 files, 147 MB, skipped=0,
  stamped=40). iluminatecz idempotent re-confirm (104 files, stamped=0, keeps its
  18:14 clock, drive_id `1PQFChv7...`). Insurance passed: agape purge dry-run =
  exactly 40 candidates = the archived set (skipped=0 so 100% in the zip).
- [ ] **Tomorrow (2 Jul, after 20:30)**: confirm agape purged (storage_breakdown drops);
  **test recovery** — `restore_from_bundle agape <drive_id> --apply`, confirm a report
  regenerates.
- [ ] **8 Jul (after 20:30)**: confirm iluminatecz auto-purged (Notion reminder set).
- [ ] **Remove the TEMP test crons** once the experiment is done (mothball).

## Open follow-ups (deferred, in Notion)

- [ ] Report-level retry (3x) reusing synthesis artifact — decide if wanted on top
  of read-level retry (cost: LLM re-synth).
- [ ] Wire the real recurring archive/purge cron + report-success gating — only
  when a paying client is live.
- [ ] Disable scrape crons after this e2e (the mothball).
