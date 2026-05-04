# Claude_Social — Architecture Plan (Phase 1)

## Context

Andy manages social media for multiple clients and needs an automated system that:
1. **Tracks** what gets posted across accounts (Instagram first, FB/TikTok/X later),
2. **Stores** engagement as a time-series (not just a snapshot) so performance-over-time is visible,
3. **Backs up** all media (full carousels, full Reels videos) so clients can be given the originals,
4. **Classifies** each post with AI using a per-client prompt that changes often,
5. **Eventually** generates periodic client-facing reports (PDF/email — deferred to Phase 2).

Andy tried this in n8n and hit a wall because debug iteration was too slow. The move to code is for faster feedback loops with Claude. He is an **amateur** — the architecture must be approachable, not clever.

**Phase 1 scope (this plan):** Instagram only, one client, manual triggering, reliable scraper + dedupe + media backup + AI classification + solid observability. Reports are deferred.

**Design principle:** Build Phase 1 as an *honest slice* of the Phase 2 architecture — pluggable scrapers, per-platform columns, per-client config — so Phase 2 is "add files" not "rewrite."

---

## Stack decisions (with reasoning)

| Area | Choice | Why |
|---|---|---|
| **Language** | Python 3.12 | Best-in-class SDKs for Apify, Supabase, Gemini, OpenAI; strong for data/AI; approachable. |
| **Package mgr** | `uv` | Fastest modern Python tool; single `uv sync` reproduces env. |
| **Config** | `pydantic-settings` (env) + YAML (clients) | Typed env validation catches missing secrets at boot; YAML is easy to hand-edit. |
| **DB** | Supabase Postgres | Already chosen by Andy. Use `supabase-py` v2. |
| **Media storage** | Supabase Storage | Same account, one less vendor. |
| **Scraper** | Apify `apify/instagram-scraper` via `apify-client` SDK | Andy's existing tooling. |
| **AI (default)** | **Gemini 2.x** for video + images | Native video understanding, cheaper per token than GPT-4o on video. Per-post override possible. |
| **AI (fallback)** | OpenAI GPT-4.1 / GPT-4o for images | Swap per client via config. |
| **Scheduling** | **None in Phase 1** — manual CLI entrypoints | Andy picked "manual for testing." Architecture is scheduler-ready: adding APScheduler later is ~20 lines. |
| **Orchestration** | Docker + `docker-compose.yml` | VPS-portable (Hostinger works identically to the Mac M4). |
| **Logging** | `structlog` → stdout + Supabase `run_history` table | One place (DB) to see every run and its errors; stdout for live debug. |
| **Reports** | Deferred to Phase 2 — schema is ready for them | Don't let report design block scraper reliability. |

---

## Project structure

```
claude_social/
├── .env.example
├── .gitignore
├── pyproject.toml              # uv-managed, Python 3.12
├── justfile                    # `just scrape-posts example_client` etc.
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── migrations/
│   └── 0001_initial_schema.sql # run manually in Supabase SQL editor for now
├── config/
│   └── clients/
│       └── example_client/
│           ├── client.yaml         # accounts, platform, AI provider choice
│           ├── prompt.md           # AI classification prompt (editable)
│           └── categories.yaml     # allowed category list + descriptions
├── src/claude_social/
│   ├── config.py                   # pydantic-settings: SUPABASE_URL, APIFY_TOKEN, GEMINI_KEY, …
│   ├── logging.py                  # structlog config, injects run_id
│   ├── db/
│   │   ├── client.py               # supabase client factory (cached)
│   │   └── queries.py              # typed CRUD helpers (upsert_post, append_metric, …)
│   ├── storage/
│   │   └── media.py                # download → Supabase Storage; path scheme
│   ├── scrapers/
│   │   ├── base.py                 # Scraper protocol: .scrape_posts(account) / .scrape_stories(account)
│   │   ├── instagram.py            # Apify `apify/instagram-scraper` wrapper
│   │   └── registry.py             # {"instagram": InstagramScraper, ...}
│   ├── ai/
│   │   ├── classifier.py           # public API: classify(post, media_sample, client_cfg)
│   │   ├── media_sampler.py        # which media to send (carousel → [0, mid, -1]; reel → full video)
│   │   └── providers/
│   │       ├── gemini.py
│   │       └── openai.py
│   ├── pipeline/
│   │   ├── ingest_posts.py         # the weekly job's core logic
│   │   ├── ingest_stories.py       # the 12h job's core logic
│   │   └── run_context.py          # opens/closes run_history row, collects per-item errors
│   └── reports/                    # Phase 2 stub — just a __init__.py for now
└── scripts/
    ├── scrape_posts.py             # `python -m scripts.scrape_posts --client example_client`
    ├── scrape_stories.py
    └── run_migration.py            # helper to push schema SQL to Supabase
```

**Why this shape:**
- `scrapers/` is a *plugin folder*. Adding TikTok = `scrapers/tiktok.py` + one line in `registry.py`. Nothing else changes.
- `ai/providers/` is the same pattern for AI vendors.
- `config/clients/` per-client directory means a new client is "copy the folder, edit the YAMLs" — no code changes.
- `pipeline/` is the only place that orchestrates; scripts are thin CLI wrappers around it.

---

## Database schema (Supabase Postgres)

Core tables — full DDL will live in `migrations/0001_initial_schema.sql`:

- **`clients`** — id, slug, name, is_active.
- **`accounts`** — id, client_id, **platform** (`instagram`/`facebook`/…), handle, platform_account_id, **is_owned** (false = competitor, ready for Phase 2), is_active. Unique on `(platform, handle)`.
- **`posts`** — id, account_id, platform, **platform_post_id** (the Instagram shortcode/ID), post_type (`image`/`carousel`/`reel`/`video`), caption, permalink, posted_at, first_seen_at, **raw_payload jsonb** (full Apify item, so we can re-derive fields later without re-scraping), ai_category, ai_analyzed_at, ai_prompt_version. Unique on `(platform, platform_post_id)` — this is the dedupe key.
- **`post_metrics`** — append-only time-series: post_id, scraped_at, like_count, comment_count, view_count, play_count, save_count. Indexed on `(post_id, scraped_at desc)`.
- **`media`** — id, post_id, slide_index (0 for singles), media_type, source_url, storage_path, duration_seconds, width, height. Unique on `(post_id, slide_index)`.
- **`stories`** + **`story_media`** — same shape as posts but separate, because stories are ephemeral and have different fields.
- **`run_history`** — every pipeline run: job_name, client_slug, started_at, finished_at, status (`running`/`success`/`partial`/`failed`), items_new, items_updated, items_failed, error_summary.
- **`run_item_errors`** — per-item failures: run_id, item_ref, stage (`scrape`/`download_media`/`ai`/`db`), error_message. **Crucial: one post failing never kills a run.**

**Why jsonb `raw_payload`:** if Apify returns a field we don't currently store and we later want it (e.g. `music.artist`), we can backfill from `raw_payload` without re-scraping — invaluable while the schema is still evolving.

**Storage path scheme:**
`media/{client_slug}/{platform}/{account_handle}/{YYYY}/{MM}/{post_id}/{slide_index}.{ext}`
— human-browseable, sortable, makes "export all of Client X's March media" a single prefix query.

---

## Pipeline flow — `ingest_posts`

```
1. open run_history row (status='running')
2. load client config from config/clients/{slug}/
3. for each Instagram account in client.yaml:
     a. call Apify actor → list of posts
     b. for each post (wrap EACH in try/except → run_item_errors):
          - lookup by (platform, platform_post_id)
          - if EXISTS: append post_metrics row (time-series). done.
          - if NEW:
              * insert posts row (with raw_payload)
              * for each media item:
                  - download from Apify URL
                  - upload to Supabase Storage
                  - insert media row
              * media_sampler.pick(post) → subset for AI
              * ai.classify(post, sample, client_cfg) → update posts.ai_*
              * append first post_metrics row
4. close run_history (status='success' if 0 errors, 'partial' if some, 'failed' if all)
```

`ingest_stories` is the same shape minus AI (stories are usually not classified; we can add it later).

**Error boundaries:** every per-post block is isolated. A 403 on one media download records to `run_item_errors` and moves on. The run finishes `partial`, not crashed.

---

## AI classification — how per-client prompts work

1. `config/clients/{slug}/prompt.md` — the system prompt template. Jinja-style `{{categories}}` placeholder.
2. `config/clients/{slug}/categories.yaml` — list of `{name, description}` categories for that client.
3. `client.yaml` picks provider (`gemini` or `openai`) and declares a `prompt_version` string (e.g. `"v1"` or a git-style hash).
4. `classifier.classify()`:
   - renders prompt with categories,
   - samples media via `media_sampler` (carousels → first+middle+last, Reels/videos → full video, single image → the image),
   - calls provider,
   - returns `{category, confidence, reasoning}` stored on the post along with `prompt_version`.

**Why files not DB:** Andy wants to iterate on prompts often. Files are editable in any editor, diffable in git, and `prompt_version` lets us know which posts were classified under which prompt — so re-classification is targetable.

---

## Critical files to create

All new (greenfield project):

1. `pyproject.toml`, `.env.example`, `.gitignore`, `justfile`, `docker/Dockerfile`, `docker/docker-compose.yml`
2. `migrations/0001_initial_schema.sql`
3. `src/claude_social/config.py`, `logging.py`
4. `src/claude_social/db/client.py`, `db/queries.py`
5. `src/claude_social/storage/media.py`
6. `src/claude_social/scrapers/base.py`, `scrapers/instagram.py`, `scrapers/registry.py`
7. `src/claude_social/ai/classifier.py`, `ai/media_sampler.py`, `ai/providers/gemini.py`, `ai/providers/openai.py`
8. `src/claude_social/pipeline/run_context.py`, `pipeline/ingest_posts.py`, `pipeline/ingest_stories.py`
9. `scripts/scrape_posts.py`, `scripts/scrape_stories.py`, `scripts/run_migration.py`
10. `config/clients/example_client/client.yaml`, `prompt.md`, `categories.yaml`

---

## Build order (when we exit plan mode)

A logical order that keeps each step testable:

1. **Skeleton** — `pyproject.toml`, folders, `.env.example`, `config.py` with every secret declared and validated.
2. **Migration + Supabase connection** — write DDL, run it, prove we can read/write with `db/client.py`.
3. **Scraper** — `scrapers/instagram.py` calling Apify, returning typed objects. Test against one real account with `--limit 3`.
4. **Storage** — media download + Supabase Storage upload, path scheme. Test with one post's media.
5. **Pipeline (no AI yet)** — `ingest_posts` end-to-end *without* AI. Prove dedupe + time-series + run_history.
6. **AI layer** — Gemini provider, classifier, media sampler. Wire into pipeline.
7. **Stories pipeline** — mostly a copy of the posts pipeline.
8. **Dockerize** — Dockerfile + compose, run the same commands inside the container.
9. **Phase 2 prep** — stub `reports/`, document how to add a new platform/client.

Each step = a commit + a quick manual verification.

---

## Verification (end-to-end smoke test)

After the full build:

1. `uv sync` → `cp .env.example .env` → fill Supabase + Apify + Gemini keys.
2. Paste `migrations/0001_initial_schema.sql` into Supabase SQL editor, run.
3. Edit `config/clients/example_client/client.yaml` with one real Instagram handle.
4. `just scrape-posts example_client --limit 5` (or `python -m scripts.scrape_posts …`).
5. Check Supabase:
   - `posts` — 5 rows with `ai_category` filled.
   - `media` — one row per slide/video, each with a `storage_path`.
   - Storage bucket — files at `media/example_client/instagram/{handle}/…` and openable.
   - `post_metrics` — one row per post.
   - `run_history` — one `success` row.
6. **Re-run the same command** — this is the important one:
   - `posts` count unchanged,
   - `media` count unchanged (no re-downloads),
   - `post_metrics` count **doubled** (time-series working),
   - `run_history` — a second `success` row.
7. Force a failure (e.g. bad AI key for one post) → `run_history.status='partial'`, `run_item_errors` has the entry, other posts still succeed.
8. `just scrape-stories example_client` → `stories` + `story_media` populated.

---

## Explicitly out of scope for Phase 1

- Report generation (PDF/email) — schema is ready, code deferred.
- Scheduling (cron/APScheduler) — manual CLI only.
- Competitor-account specific flows — the `is_owned` flag exists, but no UI/reports around it yet.
- Multi-platform scrapers — the `scrapers/` shape is ready, but only `instagram.py` is implemented.
- Web UI / admin panel — none.
- Auth beyond `.env` — single-user local tool.

---

## Open questions (ask after implementation starts, not blockers)

- Which categories should `example_client/categories.yaml` ship with as placeholders?
- Should `raw_payload` be stored encrypted? (Probably no — it's public social data — but worth confirming.)
- When we move to VPS, does Hostinger host Docker directly or do we need a VPS with SSH? (Affects deploy docs, not architecture.)
