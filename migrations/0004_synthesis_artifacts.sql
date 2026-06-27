-- Persist LLM synthesis output per client+period+platform.
-- Enables color/layout iteration without re-burning LLM calls.
-- Each report run appends a new row; history is preserved for analysis.

create table synthesis_artifacts (
    id              uuid primary key default gen_random_uuid(),
    client_slug     text not null,
    period_label    text not null,
    platform        text not null default 'instagram',
    model           text not null,
    prompt_versions jsonb not null,  -- {"pass0": "v3", "pass1": "v3", "pass2": "v4"}
    artifact        jsonb not null,  -- account_handle → category → CategorySynthesis
    created_at      timestamptz not null default now()
);

-- Supports "latest artifact for a given client+period+platform" lookup.
create index on synthesis_artifacts (client_slug, period_label, platform, created_at desc);
