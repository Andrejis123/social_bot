-- Weekly data-health history: persisted output of `data_health <interval>
-- --save` (the printed report stays the human view; these tables are the
-- machine history for trend analysis — scrape-cadence tuning per account and
-- early error-pattern detection such as rising empty-scrape rates or
-- OpenAI-describe-fallback creep).

CREATE TABLE IF NOT EXISTS health_snapshots (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at            timestamptz NOT NULL DEFAULT now(),
    interval               text NOT NULL,
    period_start           timestamptz NOT NULL,
    period_end             timestamptz NOT NULL,
    account_id             uuid NOT NULL,
    handle                 text NOT NULL,
    platform               text NOT NULL,
    -- Posts
    posts_new              integer NOT NULL DEFAULT 0,
    posts_classified       integer NOT NULL DEFAULT 0,
    posts_classify_fp      integer NOT NULL DEFAULT 0,
    posts_described        integer NOT NULL DEFAULT 0,
    posts_describe_fp      integer NOT NULL DEFAULT 0,
    posts_describe_oai     integer NOT NULL DEFAULT 0,
    post_runs_total        integer NOT NULL DEFAULT 0,
    post_runs_empty        integer NOT NULL DEFAULT 0,
    -- Stories
    stories_new            integer NOT NULL DEFAULT 0,
    stories_classified     integer NOT NULL DEFAULT 0,
    stories_classify_fp    integer NOT NULL DEFAULT 0,
    stories_described      integer NOT NULL DEFAULT 0,
    stories_describe_fp    integer NOT NULL DEFAULT 0,
    story_runs_total       integer NOT NULL DEFAULT 0,
    story_runs_empty       integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS health_snapshots_series_idx
    ON health_snapshots (handle, platform, captured_at);

CREATE TABLE IF NOT EXISTS storage_snapshots (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at timestamptz NOT NULL DEFAULT now(),
    client      text NOT NULL,
    kind        text NOT NULL,
    bytes       bigint NOT NULL,
    files       integer NOT NULL
);

CREATE INDEX IF NOT EXISTS storage_snapshots_series_idx
    ON storage_snapshots (client, kind, captured_at);
