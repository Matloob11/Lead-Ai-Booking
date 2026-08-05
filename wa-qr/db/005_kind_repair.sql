-- When this phone's `unknown` messages were re-read.
--
-- 878 rows were stored before the raw WhatsApp type was kept anywhere. Their
-- real type — a poll, a call record, an order, whatever it was — was decided to
-- be "unknown" and then thrown away, so nothing in this database can recover
-- it. Only WhatsApp still knows, and only for as long as the phone holds the
-- message.
--
-- The repair asks it, once. A marker rather than "run it whenever unknowns
-- exist", because some of them will never come back — a message the phone has
-- since dropped is gone — and without this the pass would go looking for them
-- again on every single reconnect, for ever.

ALTER TABLE qr_session
    ADD COLUMN IF NOT EXISTS kinds_repaired_at TIMESTAMPTZ;

-- The pass reads exactly this: which messages on this phone are still unknown.
CREATE INDEX IF NOT EXISTS qr_message_unknown_kind
    ON qr_message (conversation_id) WHERE kind = 'unknown';
