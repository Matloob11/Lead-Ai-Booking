/**
 * Who is asking, and what they may see.
 *
 * This service has no login of its own. It sits behind nginx, which already
 * authenticated the caller against Django, and states the answer in two
 * headers:
 *
 *   X-WA-Agent-Id : 5    accounts_agent.id of the signed-in agent
 *   X-WA-Is-Admin : 1    "1" when that agent has admin rights
 *
 * **Both headers must be set by nginx on every proxied request, and nginx must
 * strip whatever the client sent.** They are an assertion, not a claim: nothing
 * downstream can tell a header nginx wrote from one a browser typed, so if the
 * client's copy survives, any agent can read `X-WA-Is-Admin: 1` and become an
 * admin. `proxy_set_header` on both names does that — it replaces, it does not
 * append.
 *
 * A request without them is refused rather than let through as a guest. Until
 * nginx is wired, that means /api answers 401, which is the truthful state: the
 * service cannot tell who is asking, and everything behind it is somebody's
 * private conversation.
 */

const AGENT_HEADER = "x-wa-agent-id";
const ADMIN_HEADER = "x-wa-is-admin";

const TRUTHY = new Set(["1", "true", "yes", "y", "on"]);

/**
 * Reads the two headers onto `req.identity`, or refuses the request.
 *
 * Mounted on /api only — the static panel still loads, and the 401 its first
 * fetch gets is a far clearer symptom than a blank screen.
 */
export function attachIdentity(req, res, next) {
  const rawAgentId = req.get(AGENT_HEADER);
  const isAdmin = TRUTHY.has(String(req.get(ADMIN_HEADER) || "").toLowerCase());
  const agentId = Number(rawAgentId);
  const hasAgentId = rawAgentId !== undefined && Number.isInteger(agentId) && agentId > 0;

  // An admin is allowed through without an agent id — a portal administrator
  // need not be an agent — but nobody is allowed through with neither.
  if (!hasAgentId && !isAdmin) {
    return res.status(401).json({
      detail: "This request carries no identity. It must be proxied by nginx.",
    });
  }

  req.identity = { agentId: hasAgentId ? agentId : null, isAdmin };
  next();
}

/** Ends the request with 403 unless the caller is an admin. Returns whether it did. */
export function refuseNonAdmin(req, res) {
  if (req.identity?.isAdmin) return false;
  res.status(403).json({ detail: "Admins only" });
  return true;
}

/**
 * The sessions this caller may work with.
 *
 * `null` means "every one of them" — an admin. It is deliberately not an array
 * of all ids: a caller that forgets to check for null then filters by an empty
 * list and shows an admin nothing, which is a visible bug, rather than
 * filtering by a stale list and showing an agent too much, which is not.
 */
export async function visibleSessionIds(identity) {
  if (identity?.isAdmin) return null;
  if (!identity?.agentId) return [];

  const { sessionIdsForAgent } = await import("../sessions/assignments.js");
  return sessionIdsForAgent(identity.agentId);
}

/** Whether this caller may touch one particular session. */
export async function mayUseSession(identity, sessionId) {
  const allowed = await visibleSessionIds(identity);
  if (allowed === null) return true;
  return allowed.includes(Number(sessionId));
}
