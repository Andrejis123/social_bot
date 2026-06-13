# Social Bot

Automated social-media performance tracking + monthly client reports.

Currently runs Instagram posts + stories scraping → AI classification + description (Gemini) → time-series engagement storage → monthly .pptx reports published to Supabase + Google Drive. Multi-platform (FB, YouTube, TikTok) is queued behind a real-client driver.

**Live:** 3 clients × 6 active accounts, nightly stories cron + weekly posts cron, monthly report cron wired but disabled until first paying client.

## Stack

- **Mac** = dev. Edit code, push to GitHub.
- **VPS** (DigitalOcean) = runtime. Pulls from GitHub, runs in Docker on cron.
- **Supabase** = Postgres (metadata, engagement snapshots, AI fields) + Storage (media + reports).
- **HikerAPI** = primary Instagram scraping (tier 1, auth-first, sees restricted profiles).
- **Apify** = fallback Instagram scraping (tier 2/3, anonymous + cookie paths).
- **Gemini** = classify + describe pipeline + report-narrative synthesis.
- **Google Drive** = report drafts + monthly content bundles, per-client folder layout.
- **Telegram** = run notifications.

## Quick start (dev on Mac)

1. `brew install uv just`
2. `just bootstrap`
3. `cp .env.example .env` → fill `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `APIFY_TOKEN`, `GEMINI_API_KEY`, `HIKER_API_KEY`, `TELEGRAM_*`, `GOOGLE_OAUTH_*`. See `.env.example` for the full list.
4. Supabase dashboard: create a private Storage bucket called `media`; run `migrations/0001_initial_schema.sql`.
5. `just scrape-posts <client_slug> 5`

## Layout

```
src/social_bot/
  config.py        # typed env settings (pydantic-settings)
  logging.py       # structlog setup
  db/              # Supabase client + typed CRUD (only module that knows column names)
  storage/         # media + report upload to Supabase
  scrapers/        # per-platform scrapers (instagram = hiker + apify multi-tier)
  ai/              # classifier + describer (Gemini default, OpenAI fallback)
  pipeline/        # orchestration: ingest_posts, ingest_stories, describe_*
  reports/         # python-pptx renderer + Gemini synthesis (two-pass)
  drive.py         # Google Drive uploader (reports/draft + data bundles)
scripts/           # thin CLI wrappers + maintenance scripts + cron drivers
config/clients/    # one folder per client (client.yaml, prompt.md, categories.yaml)
assets/clients/    # per-client brand assets (brand.yaml + logo); _default/ is the fallback
migrations/        # SQL schema
docker/            # Dockerfile + docker-compose.yml for VPS runtime
```

## Common operations

```bash
# Manual scrape + describe for one client
just ingest <client_slug>

# Render + publish a monthly report (renders to /tmp/reports, uploads to Supabase + Drive, Telegram-notifies)
python -m scripts.run_monthly_reports <YYYY-MM-DD> <YYYY-MM-DD> <client_slug>

# Build a content bundle (zip of all scraped media for a period) → Drive
python -m scripts.make_content_bundle <client_slug> <YYYY-MM-DD> <YYYY-MM-DD>

# Mint a Google Drive refresh token (one-time, requires credentials.json from GCP)
python scripts/_google_auth.py
```

## Adding a new client

1. `cp -R config/clients/agape config/clients/<new_slug>` and edit `client.yaml`, `prompt.md`, `categories.yaml`.
2. Insert a `clients` row + `accounts` row in Supabase.
3. *(Optional)* drop `assets/clients/<new_slug>/brand.yaml` + `logo.jpg` for client-specific branding. If absent, the renderer falls back to `assets/clients/_default/`.

## Adding a new platform

1. Add `src/social_bot/scrapers/<platform>.py` implementing the `Scraper` protocol from `scrapers/base.py`.
2. Register it in `scrapers/registry.py`.
3. Add `platform: <name>` entries to client YAML files.
No DB migrations needed — schema already has a `platform` column.

## Deploy

```bash
# Local
git push origin main

# On VPS (root@<host>:/opt/social-bot)
git pull
docker compose -f docker/docker-compose.yml build
```

Crontab on the VPS drives all scheduled work; the file is owned by root and backups are kept at `/opt/social-bot/crontab.backup.*`.
