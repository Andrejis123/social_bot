# Audit fixes tracker

Working doc for implementing the top 12 changes from `AUDIT_CODEBASE.md` + `AUDIT_WORKFLOW.md`
(session 2026-07-03). If the session dies, resume from here: each item lists status, files, and
what "done" means. Protocol: bug fixes (items 3-9) get failing tests via /write-tests BEFORE the
fix; infra/refactor items (1, 2, 10, 11, 12) don't need failing tests. Finish = `just check`
green, then `/commit-session full` (commit + push + VPS deploy + deploy-check).

| # | Status | Change |
|---|--------|--------|
| 1 | DONE | `uv.lock` staged (verified current via `uv lock --check`); Dockerfile now `COPY uv.lock` + `uv sync --frozen --no-dev` (no fallback); `.gitignore` entry removed |
| 2 | DONE | `.github/workflows/check.yml`: ruff + mypy + pytest on push/PR to main, uv with `--frozen`, dummy env for required Settings fields |
| 3 | DONE | Pagination: `_fetch_all` helper in `db/queries.py` (rebuild-query-per-page); all 9 bulk listers routed through it; `list_media_for_posts`/`list_story_media_for_stories` also chunk ids by 100; `list_all_tracked_drive_ids` refactored onto the helper. Tests: tests/test_queries_pagination.py (9) |
| 4 | DONE | retry_ai now downloads blobs from storage_path (`_fetch_blobs_from_storage`, first/middle/last sampling) and passes them via new optional `blobs` param on `classifier.classify`; exhausted alerts grouped by (client, platform) instead of hardcoded instagram. Test: tests/test_retry_ai.py |
| 5 | DONE | Scrape exceptions caught inside the RunContext in both ingest pipelines: recorded via record_item_error(stage='scrape'), run finishes 'failed', remaining accounts continue. Tests: tests/test_account_isolation.py |
| 6 | DONE | `_dedupe_reel_cover` keeps at most one sentinel-99 cover per post; applied in hiker + Apify carousel normalizers. Tests in test_hiker_normalizer.py + test_instagram_normalizer.py |
| 7 | DONE | `_esc` (html.escape) applied to dynamic values in notify_report_failed / notify_archive_failed / notify_purge_failed. Tests: tests/test_telegram.py (3) |
| 8 | DONE | `_is_retryable` gates on genai_errors.APIError code in (429,500,502,503,504) for both classify_with_gemini and describe_with_gemini; old substring gate removed; legacy transient test migrated to coded APIError. Tests in test_gemini_parsing.py |
| 9 | DONE | Ambiguous --account (handle on >1 platform, no platform given) raises ValueError before any run starts; e2e test updated to the new contract. Test: test_account_isolation.py + test_pipeline_e2e.py |
| 10 | DONE | All datetime.utcnow() -> datetime.now(UTC) in db/queries.py + storage/media.py |
| 11 | DONE | `config/cron_clients.yaml` + `clients.default_cron_clients()`; both cron drivers use it (hardcoded DEFAULT_CLIENTS removed); .env.example gained GOOGLE_OAUTH_*, GOOGLE_DRIVE_*, TELEGRAM_* blocks |
| 12 | DONE | Live crontab fetched -> `deploy/crontab.txt` (mothballed state, 3 TEMP archive/purge crons); `just crontab-diff` (verified: in sync) + `just crontab-install` (backs up live first) added to justfile |

## Decisions (locked with Andy 2026-07-03)

- Scope: all 12. Deploy: `/commit-session full` incl. VPS deploy at the end.
- VPS SSH fetch of live crontab: approved (read-only).

## Log

- 2026-07-03: tracker created; work starting with items 1, 2, 12 (infra), then /write-tests for 3-9, then fixes, then 10-11.
- 2026-07-03 (later): ALL 12 DONE. /write-tests subagent produced 20 red tests (5 new files + 2 extended); all fixes landed test-first. Gate: ruff clean, mypy 0 errors, 192 tests pass. Next: /commit-session full (commit+push+deploy+deploy-check).
- 2026-07-04: /commit-session full attempted; the 4 /simplify sub-agents (and /security-review, also agent-based) blocked by the subagent session limit (resets 3:20am). Four bonus audit items landed while waiting:
  - 13 DONE: deploy_check now instantiates Settings() (env drift fails deploy-check loudly) and prints supabase/google-genai/openai/apify-client versions.
  - 14 DONE: pick_for_ai + describe_posts._sample_media_rows drop sentinel-99 reel covers unless they are the only media (cost trim; +5 tests in test_media_sampler.py).
  - 15 DONE: telegram _TZ = ZoneInfo("Europe/Bratislava") instead of fixed UTC+1 (DST-correct retry times).
  - 16 DONE: README status block (mothball state, crontab recipes, cron_clients.yaml), migration step now points at `just print-migration`; db/queries.py docstring no longer claims to be the only column-aware module.
  - Gate after all of the above: ruff clean, mypy 0 errors, 196 tests pass.
  - REMAINING: run /commit-session full after the limit resets (simplify + security-review + commit + push + deploy + deploy-check). Everything is in the working tree, nothing committed yet.
