-- Add per-post AI description columns (Phase 1.5).
-- Run in the Supabase SQL editor after 0001_initial_schema.sql.

alter table posts
    add column if not exists ai_description           text,
    add column if not exists ai_description_at        timestamptz,
    add column if not exists ai_description_attempts  integer not null default 0,
    add column if not exists ai_description_error     text;
