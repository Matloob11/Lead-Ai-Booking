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

import { q, one } from "../db.js";

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

/** Deletes a session record. */
export async function deleteSessionRecord(id) {
  await q(`DELETE FROM qr_session WHERE id = $1`, [id]);
}
