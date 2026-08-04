/**
 * Database access layer for qr_session table.
 *
 * A note on the placeholder below, because it is not obvious from the schema:
 *
 *   `phone_number` is `NOT NULL DEFAULT ''` and carries `UNIQUE
 *   (phone_number)`. A session has no number until a phone is actually linked,
 *   so two sessions waiting to be scanned would both hold '' and the second
 *   INSERT would fail on the unique index — you could never set up a second
 *   number without linking the first. Rather than change a schema three people
 *   are building against, an unlinked row carries a placeholder that cannot
 *   collide, and this module hides it again on the way out: callers see "".
 */

import { randomUUID } from "node:crypto";

import { q, one, tx } from "../db.js";

const PENDING_PREFIX = "pending-";

/** True while a row has never been linked to a real phone. */
export const isPending = (phoneNumber) => String(phoneNumber || "").startsWith(PENDING_PREFIX);

/** The number to show for a row, or "" while it is still unlinked. */
export const visibleNumber = (row) => (isPending(row?.phone_number) ? "" : row?.phone_number || "");

/** Creates a new session record in initialising state. */
export async function createSessionRecord({ label = "" } = {}) {
  const row = await one(
    `INSERT INTO qr_session (phone_number, label, status)
     VALUES ($1, $2, 'initialising')
     RETURNING *`,
    [`${PENDING_PREFIX}${randomUUID()}`, label]
  );
  return row;
}

/** Retrieves a session record by ID. */
export async function getSessionById(id) {
  return one(`SELECT * FROM qr_session WHERE id = $1`, [id]);
}

/** Retrieves a session record by phone number. */
export async function getSessionByPhoneNumber(phoneNumber) {
  return one(`SELECT * FROM qr_session WHERE phone_number = $1`, [phoneNumber]);
}

/** Retrieves all session records ordered by ID. */
export async function listAllSessions() {
  return q(`SELECT * FROM qr_session ORDER BY id ASC`);
}

/**
 * Columns a session's state may move through.
 *
 * An allowlist rather than whatever key the caller passed: field names are
 * interpolated into the statement, and this is the one place a session's
 * recorded state changes. A typo now fails loudly here instead of quietly
 * writing nothing — or worse, carrying a caller's string into the SQL.
 */
const UPDATABLE = new Set([
  "phone_number",
  "label",
  "status",
  "qr_data_url",
  "last_error",
  "last_seen_at",
  "history_status",
  "history_error",
  "history_started_at",
  "history_finished_at",
  "history_chats_total",
  "history_chats_done",
  "history_messages",
]);

/** Dynamically updates fields for a session. */
export async function updateSession(id, fields = {}) {
  const keys = Object.keys(fields);
  if (!keys.length) return getSessionById(id);

  const updates = [];
  const params = [id];
  let idx = 2;

  for (const key of keys) {
    if (!UPDATABLE.has(key)) throw new Error(`updateSession: refusing unknown column "${key}"`);
    updates.push(`${key} = $${idx}`);
    params.push(fields[key]);
    idx++;
  }

  const sql = `UPDATE qr_session SET ${updates.join(", ")} WHERE id = $1 RETURNING *`;
  return one(sql, params);
}

/**
 * Deletes a session record — and, by cascade, every conversation on it.
 *
 * Reachable from exactly one place: the merge below, after everything worth
 * keeping has already been moved off the row. Nothing in the API calls it, and
 * nothing should. A linked phone is disconnected, never deleted; the reason the
 * history is imported at all is that it must outlive whoever was carrying the
 * handset.
 */
async function deleteSessionRecord(id) {
  await q(`DELETE FROM qr_session WHERE id = $1`, [id]);
}

/**
 * Moves everything a phone accumulated onto the row that now holds that phone.
 *
 * Scanning "Link a phone" with a number that is already known opens a second,
 * empty row for it — and the months of conversation stay on the first one,
 * where nobody is looking. Rather than leave two halves of one number's history
 * side by side, the older row's contents are moved across and the emptied row
 * dropped.
 *
 * The import watermark comes across too. Without it the freshly linked row
 * would look like a first link and read six months back out of the handset for
 * messages that are already sitting in the rows it just inherited.
 *
 * One thing is knowingly lost: if an agent is already assigned to the new row,
 * the old row's *retired* assignments for that same agent go with it. Which
 * agent held the number when is worth keeping, but not at the price of a second
 * live assignment the unique index would refuse anyway.
 */
export async function adoptHistoryFrom(oldId, newId) {
  const from = Number(oldId);
  const to = Number(newId);
  if (!Number.isFinite(from) || !Number.isFinite(to) || from === to) return;

  await tx(async (client) => {
    await client.query(`UPDATE qr_conversation SET session_id = $2 WHERE session_id = $1`, [from, to]);
    await client.query(`UPDATE qr_event SET session_id = $2 WHERE session_id = $1`, [from, to]);

    await client.query(
      `UPDATE qr_session_agent AS a SET session_id = $2
        WHERE a.session_id = $1
          AND NOT EXISTS (
            SELECT 1 FROM qr_session_agent AS n
             WHERE n.session_id = $2 AND n.agent_id = a.agent_id AND n.is_active)`,
      [from, to]
    );

    await client.query(
      `UPDATE qr_session AS n SET
         label               = CASE WHEN n.label = '' THEN o.label ELSE n.label END,
         history_status      = o.history_status,
         history_finished_at = o.history_finished_at,
         history_messages    = o.history_messages
       FROM qr_session AS o
       WHERE n.id = $2 AND o.id = $1`,
      [from, to]
    );
  });

  // Outside the transaction: the row is empty now, and a cascade that finds
  // nothing to cascade to cannot take anything with it.
  await deleteSessionRecord(from);
}
