# Claude_Social

Automated social media tracking + reporting system.

**Phase 1 scope:** Instagram posts + stories, one client, manual CLI triggering, dedupe + time-series engagement + media backup + AI classification + run-history observability.

See `/Users/andy/.claude/plans/ticklish-painting-metcalfe.md` for the full architecture plan.

---

## Quick start

1. Install tools:
   ```bash
   brew install uv just
   ```
2. Bootstrap:
   ```bash
   just bootstrap
   cp .env.example .env
   # Fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, APIFY_TOKEN, GEMINI_API_KEY
   ```
3. In the Supabase dashboard:
   - Create a Storage bucket named `media` (private).
   - Open the SQL editor, paste the contents of `migrations/0001_initial_schema.sql`, run.
4. Edit `config/clients/example_client/client.yaml` with a real Instagram handle.
5. Run:
   ```bash
   just scrape-posts example_client 5   # --limit 5
   ```

## Layout

```
src/claude_social/
  config.py         # typed env settings (pydantic-settings)
  logging.py        # structlog setup
  db/               # Supabase client + typed CRUD
  storage/          # media download + upload
  scrapers/         # pluggable per-platform scrapers
  ai/               # per-client prompt-driven classifier
  pipeline/         # orchestration: ingest_posts, ingest_stories, run_context
  reports/          # Phase 2 stub
scripts/            # thin CLI wrappers: scrape_posts, scrape_stories
config/clients/     # one folder per client (YAML + prompt)
migrations/         # SQL schema
```

## Adding a new client

1. `cp -R config/clients/example_client config/clients/new_slug`
2. Edit `client.yaml`, `prompt.md`, `categories.yaml`.
3. Insert a `clients` row + `accounts` row in Supabase (or use the bootstrap script when it lands).
4. `just scrape-posts new_slug`.

## Adding a new platform

1. Add `src/claude_social/scrapers/<platform>.py` implementing the `Scraper` protocol from `scrapers/base.py`.
2. Register it in `scrapers/registry.py`.
3. Add `platform: <name>` entries to client YAML files.
No migrations needed — the schema already has a `platform` column.
