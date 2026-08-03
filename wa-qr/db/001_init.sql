-- Schema for the QR-linked channel.
--
-- Deliberately shaped like the Django models in backend/apps/inbox: the same
-- tables, the same column names where they mean the same thing. When the two
-- are joined, rows move across without a translation layer, and anyone who
-- knows one side already knows this one.

CREATE TABLE IF NOT EXISTS qr_session (
    id              BIGSERIAL PRIMARY KEY,
    -- The phone that was linked, digits only, once WhatsApp tells us.
    phone_number    TEXT        NOT NULL DEFAULT '',
    -- What an admin calls it. Same idea as WabaNumber.label.
    label           TEXT        NOT NULL DEFAULT '',
    -- initialising | qr | authenticated | ready | disconnected | banned
    status          TEXT        NOT NULL DEFAULT 'initialising',
    -- The current QR as a data URI, only while status = 'qr'.
    qr_data_url     TEXT        NOT NULL DEFAULT '',
    -- Why it stopped, when it did. Kept for the panel to show.
    last_error      TEXT        NOT NULL DEFAULT '',
    last_seen_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (phone_number)
);

CREATE TABLE IF NOT EXISTS qr_contact (
    id              BIGSERIAL PRIMARY KEY,
    wa_id           TEXT        NOT NULL UNIQUE,
    profile_name    TEXT        NOT NULL DEFAULT '',
    display_name    TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qr_conversation (
    id                   BIGSERIAL PRIMARY KEY,
    session_id           BIGINT      NOT NULL REFERENCES qr_session(id) ON DELETE CASCADE,
    contact_id           BIGINT      NOT NULL REFERENCES qr_contact(id) ON DELETE CASCADE,
    -- Groups arrive on the same socket as direct chats and have to be told
    -- apart: a group has many senders and no single customer behind it.
    is_group             BOOLEAN     NOT NULL DEFAULT FALSE,
    subject              TEXT        NOT NULL DEFAULT '',
    last_message_at      TIMESTAMPTZ,
    last_message_preview TEXT        NOT NULL DEFAULT '',
    last_message_kind    TEXT        NOT NULL DEFAULT '',
    unread_count         INTEGER     NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One thread per (linked phone, customer), matching
    -- unique_conversation_per_number on the Cloud side.
    UNIQUE (session_id, contact_id)
);

CREATE INDEX IF NOT EXISTS qr_conversation_recent
    ON qr_conversation (session_id, last_message_at DESC);

CREATE TABLE IF NOT EXISTS qr_media (
    id              BIGSERIAL PRIMARY KEY,
    -- Where the bytes landed on disk, relative to MEDIA_ROOT.
    file_path       TEXT        NOT NULL DEFAULT '',
    mime_type       TEXT        NOT NULL DEFAULT '',
    file_name       TEXT        NOT NULL DEFAULT '',
    size_bytes      BIGINT      NOT NULL DEFAULT 0,
    sha256          TEXT        NOT NULL DEFAULT '',
    downloaded      BOOLEAN     NOT NULL DEFAULT FALSE,
    download_error  TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qr_message (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT      NOT NULL REFERENCES qr_conversation(id) ON DELETE CASCADE,
    -- 'in' | 'out', spelled as on the Cloud side.
    direction       TEXT        NOT NULL,
    -- text | image | video | audio | document | sticker | location | contacts
    kind            TEXT        NOT NULL DEFAULT 'text',
    -- whatsapp-web.js's own id. Unique so a redelivered event cannot double up,
    -- which is the same guard the Cloud side puts on wamid.
    wamid           TEXT        UNIQUE,
    body            TEXT        NOT NULL DEFAULT '',
    media_id        BIGINT      REFERENCES qr_media(id) ON DELETE SET NULL,
    -- The message this one quotes, if any.
    reply_to_id     BIGINT      REFERENCES qr_message(id) ON DELETE SET NULL,
    -- {wa_id: emoji} — on the bubble it decorates, never a message of its own.
    reactions       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- In a group, who actually sent it. Empty for a direct chat.
    author_wa_id    TEXT        NOT NULL DEFAULT '',
    -- queued | sent | delivered | read | failed | received
    status          TEXT        NOT NULL DEFAULT 'received',
    error_detail    TEXT        NOT NULL DEFAULT '',
    -- Everything the library gave us, kept for kinds the UI does not model yet.
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at    TIMESTAMPTZ,
    read_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS qr_message_thread
    ON qr_message (conversation_id, created_at);

-- Every event as it arrived, before anything was made of it. The Cloud side
-- keeps WebhookEvent for the same reason: when parsing turns out to be wrong,
-- the original is still there to parse again.
CREATE TABLE IF NOT EXISTS qr_event (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT      REFERENCES qr_session(id) ON DELETE CASCADE,
    kind            TEXT        NOT NULL DEFAULT '',
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- pending | processed | ignored | failed
    status          TEXT        NOT NULL DEFAULT 'pending',
    error           TEXT        NOT NULL DEFAULT '',
    -- Whether the webhook to the Django backend went out. Null until wired.
    forwarded_at    TIMESTAMPTZ,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS qr_event_pending
    ON qr_event (status, received_at);
