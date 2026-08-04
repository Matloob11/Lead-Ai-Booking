-- Migration 004: Actions support (starred messages & deleted_at columns)

ALTER TABLE qr_message
    ADD COLUMN IF NOT EXISTS starred BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS qr_message_starred
    ON qr_message (conversation_id, created_at DESC)
    WHERE starred = TRUE;
