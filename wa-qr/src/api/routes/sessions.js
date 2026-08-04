/**
 * REST API Routes: Sessions Management
 *
 * An agent sees the phones they hold; an admin sees all of them. Creating,
 * destroying and re-assigning a phone are admin work — an agent answers on a
 * number, they do not decide who else may.
 */

import express from "express";
import * as manager from "../../sessions/manager.js";
import * as assignments from "../../sessions/assignments.js";
import { refuseNonAdmin, visibleSessionIds, mayUseSession } from "../identity.js";

const router = express.Router();

// GET /api/sessions
router.get("/", async (req, res, next) => {
  try {
    const allowed = await visibleSessionIds(req.identity);
    const all = await manager.listSessions();
    const mine = allowed === null ? all : all.filter((s) => allowed.includes(s.id));

    const rosters = await assignments.agentsForSessions(mine.map((s) => s.id));
    res.json(mine.map((session) => ({ ...session, agents: rosters[session.id] || [] })));
  } catch (err) {
    next(err);
  }
});

// POST /api/sessions
router.post("/", async (req, res, next) => {
  try {
    if (refuseNonAdmin(req, res)) return;
    const { label } = req.body || {};
    const created = await manager.createSession({ label });
    res.status(201).json({ ...created, agents: [] });
  } catch (err) {
    next(err);
  }
});

// POST /api/sessions/:id/disconnect
//
// There is deliberately no DELETE. A phone is unlinked, never removed: the row
// is what every conversation on it hangs from, and dropping it would take the
// history with it by cascade — which is precisely what an agent wanting a
// customer off the books would reach for. Admins only, for the same reason.
router.post("/:id/disconnect", async (req, res, next) => {
  try {
    if (refuseNonAdmin(req, res)) return;

    const session = await manager.getSession(req.params.id);
    if (!session) return res.status(404).json({ detail: "Session not found" });

    res.json(await manager.disconnectSession(session.id));
  } catch (err) {
    next(err);
  }
});

// POST /api/sessions/:id/relink — start a disconnected phone up for a new scan.
router.post("/:id/relink", async (req, res) => {
  try {
    if (refuseNonAdmin(req, res)) return;

    const session = await manager.relinkSession(req.params.id);
    if (!session) return res.status(404).json({ detail: "Session not found" });
    res.json(session);
  } catch (err) {
    res.status(400).json({ detail: err.message });
  }
});

// GET /api/sessions/:id/qr
router.get("/:id/qr", async (req, res, next) => {
  try {
    // A QR code links a phone to this service. Showing one to an agent who does
    // not hold the number would let them attach their own handset to it.
    if (!(await mayUseSession(req.identity, req.params.id))) {
      return res.status(404).json({ detail: "Session not found" });
    }

    const sess = await manager.getSession(req.params.id);
    if (!sess) {
      return res.status(404).json({ detail: "Session not found" });
    }
    res.json({
      status: sess.status,
      qr_data_url: sess.qrDataUrl || "",
    });
  } catch (err) {
    next(err);
  }
});

// PUT /api/sessions/:id/agents  { agents: [{agent_id, role}] }
//
// Replaces the whole roster; see assignments.replaceRoster. Agent ids are
// Django's and are not checked against a local table, because there is not one
// — an id that means nothing simply never matches a caller.
router.put("/:id/agents", async (req, res) => {
  try {
    if (refuseNonAdmin(req, res)) return;

    const session = await manager.getSession(req.params.id);
    if (!session) return res.status(404).json({ detail: "Session not found" });

    const roster = await assignments.replaceRoster(session.id, req.body?.agents ?? []);
    res.json({ ...session, agents: roster });
  } catch (err) {
    res.status(400).json({ detail: err.message });
  }
});

// GET /api/sessions/:id/agents
router.get("/:id/agents", async (req, res, next) => {
  try {
    if (!(await mayUseSession(req.identity, req.params.id))) {
      return res.status(404).json({ detail: "Session not found" });
    }
    res.json(await assignments.agentsForSession(req.params.id));
  } catch (err) {
    next(err);
  }
});

export default router;
