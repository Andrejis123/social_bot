# Task runner for Claude_Social. Install `just` once: `brew install just`.
# Run `just` to list tasks.

set dotenv-load := true

default:
    @just --list

# Install / sync dependencies with uv.
bootstrap:
    uv sync --all-extras

# Run the posts scraper for a client. Usage: `just scrape-posts example_client`
scrape-posts client limit="":
    uv run python -m scripts.scrape_posts --client {{client}} {{ if limit != "" { "--limit " + limit } else { "" } }}

# Generate AI descriptions for classified posts. Usage: `just describe-posts example_client`
describe-posts client sleep="3":
    uv run python -m scripts.describe_posts --client {{client}} --sleep {{sleep}}

# Scrape posts then immediately generate descriptions (normal weekly flow).
ingest client limit="":
    just scrape-posts {{client}} {{limit}}
    just describe-posts {{client}}

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
