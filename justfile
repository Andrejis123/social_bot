# Task runner for Social Bot. Install `just` once: `brew install just`.
# Run `just` to list tasks.

set dotenv-load := true

default:
    @just --list

# Install / sync dependencies with uv.
bootstrap:
    uv sync --all-extras

# ---------------------------------------------------------------------------
# Manual / dev commands
# ---------------------------------------------------------------------------

# Scrape posts for a client (all accounts). Optional: --account, --since, --until, --limit
scrape-posts client limit="" since="" until="" account="":
    uv run python -m scripts.scrape_posts --client {{client}} \
        {{ if limit   != "" { "--limit "   + limit   } else { "" } }} \
        {{ if since   != "" { "--since "   + since   } else { "" } }} \
        {{ if until   != "" { "--until "   + until   } else { "" } }} \
        {{ if account != "" { "--account " + account } else { "" } }}

# Scrape stories for a client (all accounts). Optional: --account
scrape-stories client account="":
    uv run python -m scripts.scrape_stories --client {{client}} \
        {{ if account != "" { "--account " + account } else { "" } }}

# Generate AI descriptions for classified posts.
describe-posts client sleep="3":
    uv run python -m scripts.describe_posts --client {{client}} --sleep {{sleep}}

# Generate AI descriptions for classified stories.
describe-stories client sleep="3":
    uv run python -m scripts.describe_stories --client {{client}} --sleep {{sleep}}

# Scrape + describe (manual full run for one client, all accounts).
ingest client limit="" since="" until="":
    just scrape-posts {{client}} {{limit}} {{since}} {{until}}
    just describe-posts {{client}}

# One-time backfill from project start (2026-04-27). Run once before cron starts.
backfill client:
    just scrape-posts {{client}} "200" "2026-04-27"
    just describe-posts {{client}}

# ---------------------------------------------------------------------------
# Cron targets — called directly by crontab on the VPS.
# --since auto-computes to first day of current month (rolls over automatically).
# Accounts are scheduled individually to avoid simultaneous Apify calls.
# ---------------------------------------------------------------------------

# Posts — each account is a separate cron entry (see crontab below).
cron-posts client handle:
    uv run python -m scripts.scrape_posts \
        --client {{client}} --account {{handle}} \
        --since $(date +%Y-%m-01) --limit 200

# Descriptions — run per client after all its accounts have been scraped.
cron-describe client:
    just describe-posts {{client}}

# Stories — each account is a separate cron entry (no --since; stories expire in 24h).
cron-stories client handle:
    uv run python -m scripts.scrape_stories \
        --client {{client}} --account {{handle}}

# Story descriptions — run per client after each stories scrape cycle.
cron-describe-stories client:
    just describe-stories {{client}}

# ---------------------------------------------------------------------------
# Migrations & checks
# ---------------------------------------------------------------------------

# Print all migration SQL (paste into Supabase SQL editor).
print-migration:
    @cat migrations/0001_initial_schema.sql
    @cat migrations/0002_add_ai_description.sql
    @cat migrations/0003_add_stories_ai.sql

# Lint + type check + tests.
check:
    uv run ruff check .
    uv run mypy src
    uv run pytest -q

fmt:
    uv run ruff format .
    uv run ruff check --fix .
