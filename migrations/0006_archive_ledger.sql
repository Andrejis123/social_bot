-- Archive ledger: track which media bytes have been bundled to Google Drive and
-- purged from Supabase Storage. The row survives the purge (carrying archived_at +
-- archive_drive_id) so it doubles as the gating ledger: purge only ever tombstones
-- rows proven to live inside a verified Drive bundle. After tombstone, storage_path
-- is NULLed (the bytes are gone from the bucket; the bundle in Drive is the copy).

ALTER TABLE media
    ADD COLUMN IF NOT EXISTS archived_at      timestamptz,
    ADD COLUMN IF NOT EXISTS archive_drive_id text;

ALTER TABLE story_media
    ADD COLUMN IF NOT EXISTS archived_at      timestamptz,
    ADD COLUMN IF NOT EXISTS archive_drive_id text;

CREATE INDEX IF NOT EXISTS media_archived_idx
    ON media (archived_at)
    WHERE archived_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS story_media_archived_idx
    ON story_media (archived_at)
    WHERE archived_at IS NOT NULL;
