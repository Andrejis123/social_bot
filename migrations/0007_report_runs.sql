-- Report-run ledger: one row per successfully published report (client +
-- period). Written by publish_report after the Supabase upload succeeds.
-- The report-gated archive cron (`archive --require-report`) checks this
-- table before bundling a period, so media whose report never landed is
-- never archived — and therefore never becomes purge-eligible.

CREATE TABLE IF NOT EXISTS report_runs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_slug  text NOT NULL,
    period_start date NOT NULL,
    period_end   date NOT NULL,
    platform     text,
    slide_count  integer NOT NULL,
    bytes_size   bigint NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS report_runs_lookup_idx
    ON report_runs (client_slug, period_start, period_end);
