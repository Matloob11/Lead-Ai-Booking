-- Who works which linked phone.
--
-- Shaped after catalog.NumberAssignment on the Cloud side, down to the word
-- "role" and the values in it: the two channels are the same idea — a phone,
-- and the agents who hold it — and an admin should not have to learn a second
-- vocabulary because the transport differs.
--
-- `agent_id` is deliberately not a foreign key. There is no user table here and
-- there is not going to be one: agents live in Django's accounts_agent, that is
-- the only place they are created, and a copy of them in this database would be
-- a second truth to keep in step. The id is carried, never resolved locally.

CREATE TABLE IF NOT EXISTS qr_session_agent (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT      NOT NULL REFERENCES qr_session(id) ON DELETE CASCADE,
    -- accounts_agent.id in the Django database. See above.
    agent_id        BIGINT      NOT NULL,
    -- primary | backup, as NumberAssignment.Role spells them.
    role            TEXT        NOT NULL DEFAULT 'primary',
    -- An assignment is never deleted, only retired. Which agent held a number
    -- when a particular conversation happened is the question asked months
    -- later, and a DELETE is the one answer that cannot be given.
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One live assignment per (phone, agent) — the retired rows are free to repeat,
-- which is what lets an agent be given a number back after handing it over.
-- Partial, for the same reason unique_active_number_agent is partial.
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_session_agent
    ON qr_session_agent (session_id, agent_id) WHERE is_active;

-- The question asked on every request once scoping is on: which phones is this
-- agent allowed to see?
CREATE INDEX IF NOT EXISTS qr_session_agent_by_agent
    ON qr_session_agent (agent_id) WHERE is_active;
