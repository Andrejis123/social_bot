-- Add AI analysis columns to stories table (Phase 1.5).
-- Run in the Supabase SQL editor after 0002_add_ai_description.sql.

alter table stories
    add column if not exists ai_category           text,
    add column if not exists ai_confidence         numeric,
    add column if not exists ai_reasoning          text,
    add column if not exists ai_analyzed_at        timestamptz,
    add column if not exists ai_prompt_version     text,
    add column if not exists ai_provider           text,
    add column if not exists ai_attempts           integer not null default 0,
    add column if not exists ai_last_error         text,
    add column if not exists ai_description        text,
    add column if not exists ai_description_at     timestamptz,
    add column if not exists ai_description_attempts integer not null default 0,
    add column if not exists ai_description_error  text;
