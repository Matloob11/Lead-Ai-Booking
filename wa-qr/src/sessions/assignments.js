/**
 * Which agents hold which linked phone.
 *
 * The rules are the Cloud side's rules, deliberately: an assignment is
 * ownership, not a filter. An agent assigned to a phone sees **every**
 * conversation on it, not only the ones they answered — because the agent hands
 * that number to the customer themselves, and a colleague picking up while they
 * are out is normal. What the assignment decides is which *phones* an agent can
 * reach at all.
 *
 * Agents themselves are Django's; see db/002_assignments.sql.
 */

import { q, one } from "../db.js";

const ROLES = new Set(["primary", "backup"]);

/** The roster for one session, active rows only. */
export async function agentsForSession(sessionId) {
  return q(
    `SELECT agent_id, role, created_at
       FROM qr_session_agent
      WHERE session_id = $1 AND is_active
      ORDER BY role, agent_id`,
    [Number(sessionId)]
  ).then((rows) =>
    rows.map((row) => ({ agent_id: Number(row.agent_id), role: row.role }))
  );
}

/**
 * Rosters for many sessions at once, as `{sessionId: [...]}`.
 *
 * One query rather than one per session: the list screen asks for all of them
 * every time it repaints.
 */
export async function agentsForSessions(sessionIds = []) {
  const ids = sessionIds.map(Number).filter(Number.isFinite);
  const grouped = Object.fromEntries(ids.map((id) => [id, []]));
  if (!ids.length) return grouped;

  const rows = await q(
    `SELECT session_id, agent_id, role
       FROM qr_session_agent
      WHERE session_id = ANY($1::bigint[]) AND is_active
      ORDER BY role, agent_id`,
    [ids]
  );

  for (const row of rows) {
    grouped[Number(row.session_id)]?.push({
      agent_id: Number(row.agent_id),
      role: row.role,
    });
  }
  return grouped;
}

/** The sessions one agent may work. */
export async function sessionIdsForAgent(agentId) {
  const rows = await q(
    `SELECT session_id FROM qr_session_agent WHERE agent_id = $1 AND is_active`,
    [Number(agentId)]
  );
  return rows.map((row) => Number(row.session_id));
}

/**
 * Sets exactly who works a phone.
 *
 * Replaces the roster rather than adding to it, so the screen sends the state
 * it wants and does not have to work out what changed — the same contract as
 * `PUT /api/catalog/numbers/{id}/agents/` on the Cloud side.
 *
 * Anyone dropped is deactivated, never deleted.
 *
 * @param {Array<{agent_id: number, role?: string}|number>} entries
 */
export async function replaceRoster(sessionId, entries = []) {
  const id = Number(sessionId);
  if (!Number.isFinite(id)) throw new Error("A session id is required");
  if (!Array.isArray(entries)) throw new Error("agents must be a list");

  const wanted = new Map();
  for (const entry of entries) {
    const agentId = Number(entry && typeof entry === "object" ? entry.agent_id : entry);
    if (!Number.isFinite(agentId) || agentId <= 0) continue;

    const role = (entry && typeof entry === "object" && entry.role) || "primary";
    if (!ROLES.has(role)) throw new Error(`Unknown role "${role}"`);
    wanted.set(agentId, role);
  }

  const agentIds = [...wanted.keys()];

  // Retire whoever is no longer on the list. `= ALL` with an empty array is
  // true for every row, which is what clearing the roster should do.
  await q(
    `UPDATE qr_session_agent
        SET is_active = FALSE
      WHERE session_id = $1 AND is_active AND NOT (agent_id = ANY($2::bigint[]))`,
    [id, agentIds]
  );

  for (const [agentId, role] of wanted) {
    // Revives a retired row rather than adding a second one for the same pair,
    // so handing a number back does not leave two histories to read.
    const revived = await one(
      `UPDATE qr_session_agent
          SET is_active = TRUE, role = $3
        WHERE session_id = $1 AND agent_id = $2
          AND id = (SELECT id FROM qr_session_agent
                     WHERE session_id = $1 AND agent_id = $2
                     ORDER BY is_active DESC, id DESC LIMIT 1)
        RETURNING id`,
      [id, agentId, role]
    );
    if (!revived) {
      await q(
        `INSERT INTO qr_session_agent (session_id, agent_id, role) VALUES ($1, $2, $3)`,
        [id, agentId, role]
      );
    }
  }

  return agentsForSession(id);
}
