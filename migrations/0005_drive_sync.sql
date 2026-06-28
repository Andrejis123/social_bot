-- Drive sync ledger: track which media has been mirrored to Google Drive Live View.
-- Allows re-runs to skip already-synced items and retention prune to find expired ones.

ALTER TABLE media
    ADD COLUMN IF NOT EXISTS drive_file_id   text,
    ADD COLUMN IF NOT EXISTS drive_synced_at timestamptz;

ALTER TABLE story_media
    ADD COLUMN IF NOT EXISTS drive_file_id   text,
    ADD COLUMN IF NOT EXISTS drive_synced_at timestamptz;

CREATE INDEX IF NOT EXISTS media_drive_synced_idx
    ON media (drive_synced_at)
    WHERE drive_synced_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS story_media_drive_synced_idx
    ON story_media (drive_synced_at)
    WHERE drive_synced_at IS NOT NULL;
