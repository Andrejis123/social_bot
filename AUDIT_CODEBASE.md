# Social_Bot Codebase Audit

*Audit date: 2026-07-03. Verified against working tree at commit `4cdfeb3`. All claims checked against code; `just check` re-run during the audit (ruff clean, mypy 0 errors, 172 tests pass in 2.16s).*

## Files read

Everything under `src/social_bot/` (config, clients, logging, db/, storage/, scrapers/, ai/, pipeline/, reports/, notifications/, drive.py, health.py, media_optimize.py), all of `scripts/` (cron drivers, maintenance, `_spike_*` and one-offs), all 6 `migrations/*.sql`, all 13 `tests/test_*.py` plus fixtures inventory, `config/clients/*` (sample: agape), `docker/Dockerfile`, `docker/docker-compose.yml`, `justfile`, `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `CLAUDE.md`, `.claude/settings.json` + hooks, `docs/*` (archive architecture/rollout, drive live view plan, facebook brief, report template requirements, AUDIT_PROMPT, and the 2026-07-03 Claude insights report), `research/*`, git history (48 commits), and the project journal memory (cron schedule, wind-down state).

## Ranked findings

| # | Severity | Finding | Where |
|---|----------|---------|-------|
| 1 | **High** | `uv.lock` is gitignored, so the Docker build's `uv sync --frozen \|\| uv sync --no-dev` silently resolves fresh dependency versions on every VPS deploy | `.gitignore:24`, `docker/Dockerfile:22` |
| 2 | **High** | No pagination on the Supabase queries feeding reports, bundles, and purges; PostgREST caps results at 1000 rows and truncates silently | `db/queries.py:344-399,763-784`, `reports/data.py:278-306` |
| 3 | **Med** | One account's scraper exception aborts all remaining accounts in a multi-account run | `pipeline/ingest_posts.py:60-82` |
| 4 | **Med** | A carousel with 2+ video slides produces two media rows at sentinel `slide_index=99`: unique-constraint violation plus storage-path overwrite | `scrapers/instagram.py:717-723,800-811`, `migrations/0001:89` |
| 5 | **Med** | `retry_ai` re-classifies using expired CDN `source_url`s instead of `storage_path`, silently degrading retries to caption-only | `scripts/retry_ai.py:51-70` |
| 6 | **Med** | Post dedupe key is inconsistent across scraper tiers (Hiker `pk` vs Apify `id`/`shortCode` vs fallback `postId`); tier switches can re-ingest the same post under a different key | `scrapers/instagram.py:589-593,647-651` |
| 7 | **Med** | `--account` targeting matches handle only, ignoring platform and `is_active`; already caused the agape Facebook failure loop | `pipeline/ingest_posts.py:50-53`, same in `ingest_stories.py:38-40` |
| 8 | **Med** | Classifier/descriptor Gemini retry gates on substring match of `str(exc)` ("503" in message), unlike synthesis which checks the status code properly | `ai/providers/gemini.py:103-108` vs `reports/synthesis.py:462-467` |
| 9 | **Med** | Telegram alerts interpolate raw error text into HTML without escaping; a message that breaks parse mode is dropped silently, exactly when an alert matters most | `notifications/telegram.py:34-49,171-217` |
| 10 | **Med** | Entire client Live-View Drive tree is shared "anyone with the link", no expiry; report signed URLs live 10 years in Telegram history | `pipeline/sync_drive.py:146-148`, `drive.py:269-295`, `storage/reports.py:29` |
| 11 | **Low** | `datetime.utcnow()` (naive, deprecated in 3.12) used for all DB timestamps | `db/queries.py:191,253,318,490,878` etc., `storage/media.py:56` |
| 12 | **Low** | Attempt counters use read-then-write, not atomic increment | `db/queries.py:197-206,224-233,495-503` |
| 13 | **Low** | AI media sampling sends both the reel video and its cover frame; carousel first/middle/last sampling can select sentinel covers | `ai/media_sampler.py:18-24`, `pipeline/describe_posts.py:104-108` |
| 14 | **Low** | Notification timezone hardcoded UTC+1; wrong during Slovak summer time | `notifications/telegram.py:20` |
| 15 | **Low** | `RunContext.platform` defaults to `"instagram"`, so describe/sync/archive notifications can mislabel platform | `pipeline/run_context.py:36` |
| 16 | **Low** | Synthesis and Drive folder caches live inside the ephemeral `--rm` container on the VPS, so every cron run re-pays Drive folder lookups (LLM output is protected by the Supabase artifact table) | `reports/synthesis.py:55`, `drive.py:44`, `docker/docker-compose.yml:20-21` |
| 17 | **Low** | `_migrate_hiker_dedup` reads `posts` with no pagination; over 1000 rows it silently misses some | `scripts/_migrate_hiker_dedup.py:20-22` |
| 18 | **Low** | Doc drift: `.env.example` missing `TELEGRAM_*` / `GOOGLE_OAUTH_*` / `GOOGLE_DRIVE_*` that README step 3 tells you to fill; synthesis docstring claims `gemini-2.5-flash` while the default is `gemini-2.0-flash`; README claims "3 clients × 6 accounts" while `config/clients/` holds 8 folders | `.env.example`, `README.md:12,29`, `reports/synthesis.py:21`, `config.py:64` |
| 19 | **Low** | `DEFAULT_CLIENTS` list duplicated in two cron drivers; guaranteed drift when a client is added | `scripts/archive_and_purge.py:45`, `scripts/run_monthly_reports.py:37` |
| 20 | **Low** | Descriptor prompt has no untrusted-input clause (classify is enum-constrained and synthesis has one, so blast radius is small) | `ai/descriptor.py:22-41` |

Details for the top items follow; sections cover the full audit scope.

---

## 1. Architecture overview

The code is a clean layered monolith and the layering is real, with one boundary exception noted below.

**End-to-end flow traced (posts, the busiest path).** VPS cron runs `docker run ... social-bot python -m scripts.scrape_posts --client agape --account agapeslovensko --since $(date +%Y-%m-01) --limit 200` (justfile `cron-posts`). `scripts/scrape_posts.py` is a thin typer wrapper over `pipeline.ingest_posts.ingest_posts_for_client`, which loads `config/clients/agape/` YAML (`clients.py`), upserts client + account rows (`db/queries.py`), and gets a scraper from `scrapers/registry.py`. `InstagramScraper.scrape_posts` runs the three-tier cascade: HikerAPI (`_hiker_client.py`, pk cached on the account row to skip the paid username lookup), then anonymous Apify, then cookie+residential-proxy Apify, falling through only on error, never on a valid-but-empty response (a deliberate, correct cost decision documented at `instagram.py:99-103`). Each post is deduped on `(platform, platform_post_id)`; new posts insert a row, download each media item to Supabase Storage (`storage/media.py`, deterministic path scheme), classify via Gemini with OpenAI fallback (`ai/classifier.py`), and append a `post_metrics` snapshot; existing posts just get a fresh metrics row, which is what makes the time series. All of this is bookkept by `RunContext` into `run_history` + `run_item_errors` with Telegram notifications. Describe jobs run later per client, pulling media back from Storage (CDN URLs expire; storage paths don't, a lesson the code visibly internalized).

Reports: `reports/data.py` fetches and buckets a period into a `ReportData` tree, `reports/synthesis.py` runs the three-pass Gemini pipeline per (account, category) with on-disk caching and Supabase artifact persistence, `reports/renderer.py` assembles the deck via `layouts.py`/`theme.py`/`brand.py` and publishes to Supabase (10-year signed URL) + Drive draft folder + Telegram. Archive lifecycle: `make_content_bundle` zips a period from Storage, `archive_and_purge archive` uploads to Drive, verifies byte size, stamps only the paths that verifiably entered the zip; `purge` (dry-run default, grace window, empty-set abort) deletes bucket bytes and tombstones rows; `restore_from_bundle` inverts it. This chain is the best-engineered part of the codebase.

**Where reality diverges from the stated design:**

- The `db/` docstring claims it is "the only module that knows column names" (`db/queries.py:4`). Not true: `reports/data.py` (`_fetch_posts`, `_fetch_latest_metrics`, etc.), `health.py`, `storage/synthesis.py`, and several scripts (`_migrate_hiker_dedup.py`, `_cleanup_stale_junk.py`) all query tables and columns directly. The boundary is a good idea that has eroded; either move those queries into `db/queries.py` or soften the docstring so the next reader doesn't trust a false invariant.
- README says the primary Apify actor is the first tier; the code puts HikerAPI first whenever `HIKER_API_KEY` is set (README "Stack" section does get this right; `.env.example:20` still calls Apify "Primary").
- README quick start only mentions running `migrations/0001`; six migrations exist and `just print-migration` knows it.

The scraper `Scraper` Protocol + registry, normalized `ScrapedPost/ScrapedStory` shapes, and the pure-function normalizers are genuinely good design: the Facebook scraper slotted in without touching the pipeline, which validates the abstraction.

## 2. Correctness & reliability risks

**#1 Unpinned production builds (High).** `uv.lock` exists locally (428 KB) but is gitignored (`.gitignore:24`). The VPS clones from GitHub, so `uv sync --frozen` in `docker/Dockerfile:22` *always* fails there and the `|| uv sync --no-dev` fallback resolves dependencies fresh at every image rebuild. Every deploy is a silent dependency upgrade of `supabase`, `google-genai`, `openai`, `apify-client`, etc. This directly undermines `deploy-check`, whose whole purpose is catching prod-only regressions. Fix: `git rm` the ignore line, commit `uv.lock`, and delete the `||` fallback so a lockfile mismatch fails the build loudly. Five minutes, and the highest-leverage change in this audit.

**#2 Silent 1000-row truncation (High as the system grows).** supabase-py/PostgREST returns at most 1000 rows unless `.range()` is used. `list_posts_in_period`, `list_media_for_posts`, `list_stories_in_period`, `list_story_media_for_stories` (`db/queries.py:344-399`), `list_archived_purgeable` (`:763-784`), `_fetch_posts`/`_fetch_stories` in `reports/data.py`, and `health.py:_fetch_content` all lack it. Consequences differ: a truncated report is silently missing posts; a truncated bundle archives an incomplete month (the stamped-paths-only invariant protects against *purging* the missed files, so no data loss, but the archive is quietly partial); a truncated purge list self-heals on the next run. Current volume (~40 posts/account/month) is far below the cap, but nothing will warn when it isn't. The codebase already contains the correct pattern, written for exactly this reason, in `list_all_tracked_drive_ids` (`db/queries.py:888-913`): "a truncated result would misclassify tracked files as orphans, so we never rely on the implicit 1000-row cap." Extract that loop into a `_paginate(query)` helper and use it for every list query. Related: `list_media_for_posts` also sends *all* post ids in one `.in_()` URL; chunk it like `reports/data.py:_chunks` already does.

**#3 One account failure aborts the rest of the run (Med).** `ingest_posts_for_client` loops accounts with no try/except around `_ingest_one_account` (`pipeline/ingest_posts.py:71-80`), and `RunContext.__exit__` deliberately re-raises. An `ApifyApiError` or `httpx.ConnectError` for account 1 therefore skips accounts 2..N with no run_history rows for them at all. Cron mostly schedules per account, which masks this, but `just ingest <client>` and any future consolidated cron hit it. The per-post isolation inside the loop is good; the same isolation is missing one level up. Wrap the per-account call, record the failure, continue.

**#4 Duplicate reel-cover sentinel in multi-video carousels (Med).** `_hiker_media_from_item` and `_media_from_child` emit the cover at `REEL_COVER_SLIDE_INDEX = 99` for *every* video child (`scrapers/instagram.py:800-811,529-540`). A carousel with two videos yields two `ScrapedMedia` at index 99: the second storage upload overwrites the first cover (same `{post_id}/99.jpg` path, upsert=true), and the second `insert_media` violates `unique (post_id, slide_index)` (`migrations/0001:89`), landing in `run_item_errors` as noise every time such a post is scraped. Fix: only attach the cover sentinel for the *first* video child, or key covers as `99 - slide_index` style distinct sentinels plus a path scheme that includes the origin slide.

**#5 `retry_ai` retries against dead URLs (Med).** The nightly-retryable classify path rebuilds `ScrapedMedia` from `media.source_url` (`scripts/retry_ai.py:53-60`). IG/FB CDN URLs are signed and expire within hours; by retry time the downloads 403, `_fetch_media_blobs` swallows the failures (`ai/classifier.py:132-137`), and the "retry" classifies on caption alone while looking successful. The bytes are sitting in Supabase Storage; use `download_from_storage(m["storage_path"])` exactly as `describe_posts.py` does. Also note `notify_ai_exhausted(platform="instagram")` is hardcoded (`retry_ai.py:132`).

**#6 Cross-tier dedupe key (Med, uncertain).** Hiker posts key on numeric `pk` (`instagram.py:732`); the primary Apify normalizer keys on `raw.get("id") or raw.get("shortCode")` (`:589`); the fallback on `postId or shortCode` (`:647`). If any Apify path yields a shortcode where Hiker yielded a pk for the same post (which is precisely what happened historically, hence `scripts/_migrate_hiker_dedup.py`), a Hiker outage week produces duplicate post rows that then double-count in reports. I could not verify the current Apify actors' `id` semantics from fixtures alone, so flagging as a risk, not a confirmed bug: consider normalizing to pk when `raw` carries one, or adding a reconciliation check to `/data-health`.

**#7 `--account` cross-platform match (Med).** Documented in the project journal as the root cause of the agape Facebook failure loop and "fixed" by deleting the config block, but the mechanism remains: `[a for a in loaded.config.accounts if a.handle == account_handle]` ignores platform and `is_active` (`ingest_posts.py:52`). The cron recipes pass only handles. Add `--platform` to the cron targets or make the account filter respect the platform of the cron entry.

**#8 Retry-classification brittleness (Med).** `classify_with_gemini` decides retryability by substring: `any(code in msg for code in ("503", "429", ...))` (`gemini.py:105`). A transient error whose message happens to lack those tokens aborts immediately and burns one of the post's 3 lifetime attempts; a fatal error whose message *contains* "429" (e.g. inside a quoted payload) retries pointlessly. `reports/synthesis.py:462-467` already does it right via `genai_errors.APIError.code`. Unify on that.

**Also worth knowing (not bugs today):** Apify `.call()` has no explicit timeout (a hung actor run hangs the cron slot until Apify's own limits kick in); stories `expires_at` synthesized as posted+24h when absent is fine; `_ts_outside_window` treating unparseable timestamps as in-window is a defensible documented choice; `finish_run` failures are logged not raised, so a `run_history` row can stay `running` forever, and nothing alerts on stuck-running rows.

## 3. Security & secrets

The basics are right: `.env`, `credentials.json`, and `.drive_folder_cache.json` are all gitignored and verifiably absent from git history (`git log --all -- credentials.json` is empty); Drive scope is the minimal `drive.file`; the Telegram bot is one-way; Jinja prompt rendering uses `StrictUndefined` and passes captions as data, not re-parsed templates; synthesis prompts carry an explicit untrusted-evidence clause with versioned prompts, and classification output is schema-constrained to the category enum. That is a genuinely above-average prompt-injection posture for a scraping pipeline.

Findings, in priority order:

- **Public-by-link client media trees (Med).** `sync_client_to_drive` calls `share_folder_anyone` on every run (`pipeline/sync_drive.py:147`), making all scraped media, including competitor content for `ecig-monitoring`, readable by anyone holding the link, indefinitely. Report signed URLs are valid 10 years (`storage/reports.py:29`) and posted into Telegram chat history. Both are deliberate delivery mechanisms, but the exposure should be a per-client config flag (`live_view_public: true`) rather than unconditional, and a leaked link is irrevocable in practice unless you rotate the folder. Decide this consciously per client, especially for competitor-monitoring content you don't own.
- **Unescaped HTML in Telegram (Med, reliability-flavored).** Error strings go into `<code>{error}</code>` unescaped (`telegram.py:183,216,237`). An error containing `<` or `&` (HTML in an HTTP error body, say) makes Telegram reject the message with a 400, `send` swallows it (`:48`), and the failure alert never arrives. `html.escape()` at the top of `send` or on each interpolation.
- **Service-role key everywhere (Low).** Single `SUPABASE_SERVICE_KEY` bypassing RLS is normal for a server-side worker, but it lives in `.env` on the VPS as root and in Mac dev; there is no rotation story. Acceptable at this scale; write down the rotation procedure before the first paying client.
- **`raw_payload` retention (Low).** Full scraper payloads stored in jsonb forever include third-party data beyond what reports need (tagged users, location metadata). Not a vulnerability, but a data-minimization question if GDPR ever matters for competitor monitoring in the EU, which this is.
- Drive query strings escape `'` correctly (`drive.py:101`); inputs are your own config slugs, so injection surface is nil in practice.

## 4. Data & state

**The archive/purge/restore chain is the strongest subsystem.** Concretely verified properties: bundles are all-or-nothing (`archive_and_purge.py:73-79` aborts on any skipped download, nothing stamped); upload verified by byte size before stamping (`:86-93`); only paths that entered the verified zip are stamped (`make_content_bundle.py:44-50` written_paths contract); stamping is idempotent via the `archived_at IS NULL` guard so the grace clock never resets (`db/queries.py:745-760`); purge is dry-run by default, gated on grace days, aborts on an empty candidate set (`archive_and_purge.py:169-170`); tombstones keep the ledger row pointing at the Drive copy; restore is guarded to only touch purged rows of the right bundle (`db/queries.py:787-821`); the orphan sweep refuses to run against an empty tracked set (`sync_drive.py:276-279`); `restore_from_bundle` rejects traversal-shaped arcnames (`restore_from_bundle.py:55`). All of this is tested (23 tests in `test_archive_purge.py` including a round-trip). Two residual gaps: the live restore test has not been run against prod yet (journal, "Still pending"), and purge deletes bucket bytes *before* tombstoning (`archive_and_purge.py:174-175`), so a crash between the two leaves rows pointing at deleted objects until the next purge run re-lists and heals them; harmless but worth knowing.

**Idempotency elsewhere:** post dedupe on `(platform, platform_post_id)` with metrics-append for existing posts is correct and replay-safe; story ingest skips known stories entirely; media storage uploads are upsert; Drive Live sync is ledgered by `drive_file_id`/`drive_synced_at` with `overwrite=True` uploads, so re-runs don't duplicate. The known weak points are findings #4 (sentinel collision) and #6 (cross-tier key).

**Metrics semantics:** `post_metrics` appends one snapshot per scrape; with weekly post crons, "latest metrics" for a report is at most ~6 days stale for late-month posts, and `_fetch_latest_metrics` correctly reduces to the newest snapshot per post. The "Additional Data" cards (fastest-growing post etc.) correctly acknowledge they need ≥2 snapshots in 24h, which the current cadence cannot supply; they are honest placeholders.

**Naive timestamps (Low):** every write path uses `datetime.utcnow().isoformat()` (no offset). Supabase parses these as UTC by convention today, but `utcnow` is deprecated and one column comparison against a tz-aware value in Python (not SQL) would misbehave. Mechanical fix: `datetime.now(UTC)` everywhere; `mark_media_synced` already does it right (`db/queries.py:657-670`).

## 5. Performance & cost

Real money flows per HikerAPI request ($0.60/1k), per Apify actor run, and per Gemini call. The code is visibly cost-aware in the right places: pk caching halves Hiker request count on stories (`instagram.py:24-27`); pagination stops at the window edge with pinned-post handling (`_hiker_client.py:159-199`); empty-but-valid Hiker responses do *not* trigger paid Apify fallback (`instagram.py:99-103`); the fallback gate keys on raw item count so a normalizer bug can't trigger paid runs (`:126-129`); carousel AI sampling caps at 3 slides; synthesis has thinking disabled, per-pass caching, and Supabase artifact reuse for re-renders; Live-View media is transcoded to 480p before Drive upload.

Remaining waste, roughly ordered by dollar impact:

1. **Classify downloads video bytes it may not use** (`ai/classifier.py:118-137`): full reel mp4s are downloaded, then dropped at the provider if >18 MB (`gemini.py:59-64`) or if the provider is OpenAI (skips all video). Bandwidth, not API dollars, but on the VPS it is also time. Check size/provider before downloading.
2. **Reel classification sends video + cover frame** (finding #13): the cover is a keyframe of the video already being sent; dropping sentinel-99 items from `pick_for_ai` trims ~1 image per reel per classify and describe call.
3. **Ephemeral caches in the container** (finding #16): every cron container re-does Drive folder resolution (`_find_child_folder` list calls per path segment) because `.drive_folder_cache.json` dies with the container. Mount a small cache volume or accept it; the synthesis LLM cache matters less since artifacts persist in Supabase.
4. **`increment_*_attempts` is 2 round trips** per failure and `_describe_one` fetches media rows per post; both trivial at current volume.
5. `health.py` runs ~4 queries per account (N+1 over accounts); fine for 8 accounts, don't scale it naively.

## 6. Testing gaps

172 tests, 2.16s, all pure-unit with monkeypatched Supabase, fixtures for both Hiker response shapes (v1/v2) and both platforms. Normalizers, archive/purge/restore, drive sync helpers, synthesis parsing/hardening, and pipeline error isolation are well covered. What is *not* covered maps closely to the bugs above, which is the point:

- **`tests/test_instagram_scraper_tiering.py` (missing):** the tier cascade itself: Hiker error → Apify fallthrough, empty-Hiker → no fallback, raw-count gating, admission-gate → backup cookie. This is the most intricate cost-bearing logic in the repo and only its normalizers are tested.
- **`tests/test_hiker_client.py` (expand, currently 4 tests):** pagination stop conditions (`stop_since` with pinned posts, `max_pages_hit`, `page_id` fallthrough), 404-retry behavior, 5xx→retry→`HikerTransient`.
- **`tests/test_retry_ai.py` (missing):** would have caught finding #5 immediately (assert blobs come from storage, not source_url).
- **`tests/test_queries_pagination.py` (missing):** simulate a 1000-row page and assert list helpers keep paging; locks in the fix for finding #2.
- **`tests/test_multi_video_carousel.py` (missing, or extend `test_hiker_normalizer.py`):** carousel with two video children; asserts unique slide indices; catches finding #4.
- **`tests/test_telegram.py` (missing):** `send` escapes HTML; error strings with `<`/`&` still deliver.
- **Renderer/layouts have zero tests.** Full-deck golden tests are low-value, but `_clean_text`, `_split_caption`, `format_metric`, `_build_intro_body`, `_resolve_cluster_image` fallback ordering, and pagination-into-pages are pure functions begging for 20 cheap tests; the collab-card and image-dedupe logic has already needed fixes (commit `6d7f562`).
- **No integration smoke against real Supabase.** Everything mocks the client, so query *syntax* (PostgREST embedded joins like `posts!inner(...)`) is never exercised by CI; a typo there ships. One opt-in `pytest -m integration` against the dev project would close that.

## 7. Maintainability

- **Dead/stale code:** 7 `_spike_*.py` scripts, `pilot_cookie_scraper.py` (whose own docstring says "delete or move once decided"), `_gen_docs.py` writing to a gitignored `Documents/`, and completed one-offs (`_backfill_reel_covers.py`, `_cleanup_stale_junk.py`, `_migrate_hiker_dedup.py`, `backfill_storage_paths.py`). The `_` prefix convention does its job of marking them non-cron, but the pile obscures the ~12 scripts that matter. Move finished one-offs to `scripts/archive/` (or delete; git remembers).
- **Config sprawl:** `config/clients/` has 8 folders; journal says 3 live clients. `nasa`, `testing`, `dennikn`, `denniksme`, `policiaslovakia`, `tullysbarcarlow` are demos/experiments sitting where `DEFAULT_CLIENTS` lists and future automation look. Mark them (e.g. `_inactive/` subfolder) or prune.
- **Duplication:** `DEFAULT_CLIENTS` in two scripts (finding #19); story storage-path building + `_ext_from_url` in `ingest_stories.py` duplicate `storage/media.py` logic with a comment acknowledging it ("shared module is premature"), which was a fair call then and is borderline now; classify/classify_story and the two Gemini call sites in `gemini.py` are near-copies.
- **Naming/consistency:** good throughout; structlog events are grep-able and consistent (`hiker.*`, `apify.*`, `archive.*`). Root-level clutter (`v1_plan.md`, two PDFs, one 6 MB) belongs out of the repo root.
- **Dependencies:** modern and minimal for what it does; `jinja2` is used only for the classify prompt template and `typer` mixes with two argparse/sys.argv scripts (`restore_from_bundle.py`, `backfill_storage_paths.py`), harmless inconsistency. mypy strictness is real (0 errors, per-module ignores documented with reasons in `pyproject.toml`).

---

## If you only do 3 things

1. **Commit `uv.lock` and delete the `|| uv sync --no-dev` fallback in the Dockerfile** so prod builds are reproducible and lockfile drift fails loudly (finding #1).
2. **Add a pagination helper in `db/queries.py` and route every list query through it**, copying the pattern already written in `list_all_tracked_drive_ids` (finding #2).
3. **Fix `retry_ai` to fetch media from `storage_path`** so classification retries actually see the images they are retrying for (finding #5).
