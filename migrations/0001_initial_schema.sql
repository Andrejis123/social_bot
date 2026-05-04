-- Claude_Social — initial schema (Phase 1).
-- Paste this into the Supabase SQL editor and run.
-- Assumes `gen_random_uuid()` is available (it is, via pgcrypto on Supabase).

-- =========================
-- Clients and accounts
-- =========================

create table if not exists clients (
    id          uuid primary key default gen_random_uuid(),
    slug        text unique not null,
    name        text not null,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now()
);

create table if not exists accounts (
    id                  uuid primary key default gen_random_uuid(),
    client_id           uuid not null references clients(id) on delete cascade,
    platform            text not null,           -- 'instagram' | 'facebook' | 'tiktok' | 'x'
    handle              text not null,           -- e.g. 'nike' (no leading @)
    platform_account_id text,                    -- stable platform-side ID once we see it
    is_owned            boolean not null default true,   -- false = competitor account
    is_active           boolean not null default true,
    created_at          timestamptz not null default now(),
    unique (platform, handle)
);
create index if not exists accounts_client_idx on accounts (client_id);
create index if not exists accounts_platform_active_idx on accounts (platform, is_active);

-- =========================
-- Posts (deduped across runs)
-- =========================

create table if not exists posts (
    id                  uuid primary key default gen_random_uuid(),
    account_id          uuid not null references accounts(id) on delete cascade,
    platform            text not null,
    platform_post_id    text not null,           -- Instagram shortcode/ID
    post_type           text not null,           -- 'image' | 'carousel' | 'reel' | 'video'
    caption             text,
    permalink           text,
    posted_at           timestamptz,
    first_seen_at       timestamptz not null default now(),
    raw_payload         jsonb,                   -- full scraper item for future re-derivation
    ai_category         text,
    ai_confidence       numeric,
    ai_reasoning        text,
    ai_analyzed_at      timestamptz,
    ai_prompt_version   text,
    ai_provider         text,                    -- 'gemini' | 'openai'
    unique (platform, platform_post_id)
);
create index if not exists posts_account_posted_idx on posts (account_id, posted_at desc);

-- =========================
-- Post metrics — append-only time-series
-- =========================

create table if not exists post_metrics (
    id              bigserial primary key,
    post_id         uuid not null references posts(id) on delete cascade,
    scraped_at      timestamptz not null default now(),
    like_count      integer,
    comment_count   integer,
    view_count      integer,
    play_count      integer,
    save_count      integer,
    share_count     integer
);
create index if not exists post_metrics_post_time_idx on post_metrics (post_id, scraped_at desc);

-- =========================
-- Media files (one row per slide / video)
-- =========================

create table if not exists media (
    id                  uuid primary key default gen_random_uuid(),
    post_id             uuid not null references posts(id) on delete cascade,
    slide_index         integer not null default 0,   -- 0 for single-image posts
    media_type          text not null,                -- 'image' | 'video'
    source_url          text,                         -- original CDN URL at scrape time
    storage_path        text,                         -- Supabase Storage object path
    duration_seconds    numeric,
    width               integer,
    height              integer,
    bytes               bigint,
    downloaded_at       timestamptz,
    unique (post_id, slide_index)
);

-- =========================
-- Stories (ephemeral — separate from posts)
-- =========================

create table if not exists stories (
    id                  uuid primary key default gen_random_uuid(),
    account_id          uuid not null references accounts(id) on delete cascade,
    platform            text not null,
    platform_story_id   text not null,
    posted_at           timestamptz,
    expires_at          timestamptz,
    caption             text,
    first_seen_at       timestamptz not null default now(),
    raw_payload         jsonb,
    unique (platform, platform_story_id)
);

create table if not exists story_media (
    id              uuid primary key default gen_random_uuid(),
    story_id        uuid not null references stories(id) on delete cascade,
    media_type      text not null,               -- 'image' | 'video'
    source_url      text,
    storage_path    text,
    duration_seconds numeric,
    downloaded_at   timestamptz
);
create index if not exists story_media_story_idx on story_media (story_id);

-- =========================
-- Observability: run history + per-item errors
-- =========================

create table if not exists run_history (
    id              uuid primary key default gen_random_uuid(),
    job_name        text not null,                -- 'ingest_posts' | 'ingest_stories' | 'generate_report'
    client_slug     text,
    account_handle  text,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    status          text not null default 'running',  -- 'running' | 'success' | 'partial' | 'failed'
    items_total     integer not null default 0,
    items_new       integer not null default 0,
    items_updated   integer not null default 0,
    items_failed    integer not null default 0,
    error_summary   text
);
create index if not exists run_history_job_started_idx on run_history (job_name, started_at desc);

create table if not exists run_item_errors (
    id              bigserial primary key,
    run_id          uuid not null references run_history(id) on delete cascade,
    item_ref        text,                         -- e.g. platform_post_id
    stage           text not null,                -- 'scrape' | 'download_media' | 'ai' | 'db'
    error_message   text,
    created_at      timestamptz not null default now()
);
create index if not exists run_item_errors_run_idx on run_item_errors (run_id);
