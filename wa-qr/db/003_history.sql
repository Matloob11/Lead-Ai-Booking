-- Importing what happened before we were watching.
--
-- A linked phone arrives with months of conversation already on it, and none of
-- that is in this database. That gap is the whole problem: an agent who wants a
-- deal off the books only has to delete the thread before anyone reads it, and
-- what was never imported cannot be missed.
--
-- So the first thing a newly-linked phone does is read its own history back.
-- These columns are what that run reports about itself — enough for the panel to
-- say "importing, 12 of 84 chats" rather than looking finished while it works,
-- and enough that a restart in the middle can pick up instead of starting over.

ALTER TABLE qr_session
    -- pending | running | done | failed
    --
    -- 'done' is also the mark that says the *next* run only has to collect what
    -- arrived while the phone was away. Re-reading six months on every reconnect
    -- would put the phone through that load for nothing.
    ADD COLUMN IF NOT EXISTS history_status      TEXT        NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS history_error       TEXT        NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS history_started_at  TIMESTAMPTZ,
    -- Where the next run starts from. Set when a run completes, so the gap it
    -- has to cover is exactly the time the phone spent disconnected.
    ADD COLUMN IF NOT EXISTS history_finished_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS history_chats_total INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS history_chats_done  INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS history_messages    INTEGER     NOT NULL DEFAULT 0;

-- Imported messages are written with the time they were actually sent, not the
-- time they were read off the phone, so a six-month import lands all over this
-- index rather than at the end of it. Worth having it before that happens.
CREATE INDEX IF NOT EXISTS qr_message_by_time ON qr_message (created_at);
