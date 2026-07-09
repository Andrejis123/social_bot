# Task runner for Social Bot. Install `just` once: `brew install just`.
# Run `just` to list tasks.

set dotenv-load := true

vps      := "root@161.35.170.254"
vps_path := "/opt/social-bot"

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

# Generate AI descriptions for classified posts. Optional: --account
describe-posts client account="" sleep="3":
    uv run python -m scripts.describe_posts --client {{client}} --sleep {{sleep}} \
        {{ if account != "" { "--account " + account } else { "" } }}

# Generate AI descriptions for classified stories. Optional: --account
describe-stories client account="" sleep="3":
    uv run python -m scripts.describe_stories --client {{client}} --sleep {{sleep}} \
        {{ if account != "" { "--account " + account } else { "" } }}

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

# Sync Drive Live View for a client (mirror unsynced media, prune >30d). Optional: --window-days
sync-drive client window="30":
    uv run python -m scripts.sync_drive --client {{client}} --window-days {{window}}

# Cron target: sync Drive Live View (run after describe jobs complete).
cron-sync-drive client:
    just sync-drive {{client}}

# Archive a reported period's media to Drive + stamp the verified-archived rows.
# Run on report day; mirror the report window (30-days-ago .. yesterday).
cron-archive start end:
    uv run python -m scripts.archive_and_purge archive {{start}} {{end}}

# Purge archived, grace-expired media from Supabase Storage. Dry-run unless --apply.
# Scheduled ~a week after cron-archive so there's a recovery window.
cron-purge grace="7":
    uv run python -m scripts.archive_and_purge purge --grace-days {{grace}} --apply

# ---------------------------------------------------------------------------
# Migrations & checks
# ---------------------------------------------------------------------------

# Print all migration SQL in order (paste into Supabase SQL editor).
# Zero-padded filenames sort in application order; new migrations are
# picked up automatically.
print-migration:
    @cat migrations/*.sql

# Lint + type check + tests.
check:
    uv run ruff check .
    uv run mypy src
    uv run pytest -q

fmt:
    uv run ruff format .
    uv run ruff check --fix .

# ---------------------------------------------------------------------------
# Deploy — the VPS cron runs each job as `docker run ... social-bot python -m
# scripts.<x>`, i.e. from the BUILT image `social-bot:latest`. A `git pull`
# alone does NOT update running code — the image MUST be rebuilt. Only config/
# is volume-mounted (docker/docker-compose.yml), so YAML/prompt edits take
# effect without a rebuild; src/, scripts/, assets/, migrations/ are baked in.
# ---------------------------------------------------------------------------

# Pull latest main on the VPS and rebuild the image. Run after `git push`.
deploy:
    ssh {{vps}} 'cd {{vps_path}} && git pull && docker compose -f docker/docker-compose.yml build'
    @echo "Deployed. Smoke-test with: just deploy-check"

# Confirm the freshly built image actually contains the new code AND the two
# prod-only regressions we've been bitten by (dev-only python-pptx, missing
# assets/ COPY). Check logic lives in scripts/deploy_check.py — extend it there.
deploy-check:
    ssh {{vps}} 'cd {{vps_path}} && docker run --rm --env-file .env social-bot python -m scripts.deploy_check'

# ---------------------------------------------------------------------------
# Crontab — deploy/crontab.txt is the versioned source of truth. The VPS
# crontab is server-side state; edit the file here, then install. Always
# diff first: a live edit made over SSH that was never committed would be
# silently overwritten by install.
# ---------------------------------------------------------------------------

# Show drift between the committed crontab and what's live on the VPS.
crontab-diff:
    ssh {{vps}} 'crontab -l' | diff -u - deploy/crontab.txt && echo "crontab in sync" || true

# Install deploy/crontab.txt as the VPS crontab (backs up the live one first).
crontab-install:
    ssh {{vps}} 'crontab -l > {{vps_path}}/crontab.backup.$(date +%Y%m%d-%H%M%S)'
    ssh {{vps}} 'crontab -' < deploy/crontab.txt
    @echo "Installed deploy/crontab.txt on the VPS."
