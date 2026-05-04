# Task runner for Claude_Social. Install `just` once: `brew install just`.
# Run `just` to list tasks.

set dotenv-load := true

default:
    @just --list

# Install / sync dependencies with uv.
bootstrap:
    uv sync --all-extras

# Run the posts scraper for a client. Usage: `just scrape-posts example_client`
# Optional: since="2026-04-27" until="2026-05-03"
scrape-posts client limit="" since="" until="":
    uv run python -m scripts.scrape_posts --client {{client}} \
        {{ if limit != "" { "--limit " + limit } else { "" } }} \
        {{ if since != "" { "--since " + since } else { "" } }} \
        {{ if until != "" { "--until " + until } else { "" } }}

# Generate AI descriptions for classified posts. Usage: `just describe-posts example_client`
describe-posts client sleep="3":
    uv run python -m scripts.describe_posts --client {{client}} --sleep {{sleep}}

# Scrape posts then immediately generate descriptions (normal weekly flow).
ingest client limit="" since="" until="":
    just scrape-posts {{client}} {{limit}} {{since}} {{until}}
    just describe-posts {{client}}

# Weekly cron targets — one per client, staggered. Called by crontab on the VPS.
weekly-ecig:
    just ingest ecig-monitoring "" "$(date -d '8 days ago' +%Y-%m-%d)"
weekly-iluminatecz:
    just ingest iluminatecz "" "$(date -d '8 days ago' +%Y-%m-%d)"
weekly-agape:
    just ingest agape "" "$(date -d '8 days ago' +%Y-%m-%d)"

# Run the stories scraper for a client.
scrape-stories client:
    uv run python -m scripts.scrape_stories --client {{client}}

# Print the migration SQL so you can paste it into the Supabase SQL editor.
print-migration:
    @cat migrations/0001_initial_schema.sql
    @cat migrations/0002_add_ai_description.sql

# Lint + type check + tests.
check:
    uv run ruff check .
    uv run mypy src
    uv run pytest -q

fmt:
    uv run ruff format .
    uv run ruff check --fix .
