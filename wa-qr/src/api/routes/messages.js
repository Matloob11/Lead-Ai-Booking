/**
 * REST API Routes: Message Actions (Star / Unstar, Starred List, Search)
 */

import express from "express";
import { q, one } from "../../db.js";
import { visibleSessionIds, mayUseSession } from "../identity.js";

const router = express.Router();

// GET /api/messages/starred?session_id=
router.get("/starred", async (req, res, next) => {
  try {
    const allowedSessions = await visibleSessionIds(req.identity);

    // If non-admin agent has 0 assigned sessions
    if (Array.isArray(allowedSessions) && allowedSessions.length === 0) {
      return res.json([]);
    }

    const sessionIdParam = req.query.session_id ? Number(req.query.session_id) : null;
    if (sessionIdParam) {
      const allowed = await mayUseSession(req.identity, sessionIdParam);
      if (!allowed) {
        return res.status(403).json({ detail: "Forbidden: session access denied" });
      }
    }

    const rows = await q(
      `SELECT
         m.id,
         m.conversation_id,
         m.direction,
         m.kind,
         m.wamid,
         m.body,
         m.starred,
         m.created_at,
         conv.session_id,
         c.wa_id AS contact_wa_id,
         c.display_name AS contact_name
       FROM qr_message m
       JOIN qr_conversation conv ON m.conversation_id = conv.id
       JOIN qr_contact c ON conv.contact_id = c.id
       WHERE m.starred = TRUE
         AND ($1::bigint[] IS NULL OR conv.session_id = ANY($1::bigint[]))
         AND ($2::bigint IS NULL OR conv.session_id = $2::bigint)
       ORDER BY m.created_at DESC
       LIMIT 100`,
      [allowedSessions, sessionIdParam]
    );

    const messages = rows.map((r) => ({
      id: Number(r.id),
      conversation_id: Number(r.conversation_id),
      session_id: Number(r.session_id),
      direction: r.direction,
      kind: r.kind,
      wamid: r.wamid,
      body: r.body,
      starred: Boolean(r.starred),
      created_at: r.created_at,
      contact: {
        wa_id: r.contact_wa_id,
        name: r.contact_name || r.contact_wa_id,
      },
    }));

    res.json(messages);
  } catch (err) {
    next(err);
  }
});

// GET /api/messages/search?q=&session_id=&limit=
router.get("/search", async (req, res, next) => {
  try {
    const searchQuery = String(req.query.q || "").trim();
    if (!searchQuery) {
      return res.json([]);
    }

    const allowedSessions = await visibleSessionIds(req.identity);
    if (Array.isArray(allowedSessions) && allowedSessions.length === 0) {
      return res.json([]);
    }

    const sessionIdParam = req.query.session_id ? Number(req.query.session_id) : null;
    if (sessionIdParam) {
      const allowed = await mayUseSession(req.identity, sessionIdParam);
      if (!allowed) {
        return res.status(403).json({ detail: "Forbidden: session access denied" });
      }
    }

    const limit = Math.min(100, Math.max(1, Number(req.query.limit || 40)));
    const pattern = `%${searchQuery}%`;

    const rows = await q(
      `SELECT
         m.id,
         m.conversation_id,
         m.direction,
         m.kind,
         m.wamid,
         m.body,
         m.starred,
         m.created_at,
         conv.session_id,
         c.wa_id AS contact_wa_id,
         c.display_name AS contact_name
       FROM qr_message m
       JOIN qr_conversation conv ON m.conversation_id = conv.id
       JOIN qr_contact c ON conv.contact_id = c.id
       WHERE m.body ILIKE $1
         AND m.deleted_at IS NULL
         AND ($2::bigint[] IS NULL OR conv.session_id = ANY($2::bigint[]))
         AND ($3::bigint IS NULL OR conv.session_id = $3::bigint)
       ORDER BY m.created_at DESC
       LIMIT $4`,
      [pattern, allowedSessions, sessionIdParam, limit]
    );

    const messages = rows.map((r) => ({
      id: Number(r.id),
      conversation_id: Number(r.conversation_id),
      session_id: Number(r.session_id),
      direction: r.direction,
      kind: r.kind,
      wamid: r.wamid,
      body: r.body,
      starred: Boolean(r.starred),
      created_at: r.created_at,
      contact: {
        wa_id: r.contact_wa_id,
        name: r.contact_name || r.contact_wa_id,
      },
    }));

    res.json(messages);
  } catch (err) {
    next(err);
  }
});

// POST /api/messages/:id/star { starred: true|false }
router.post("/:id/star", async (req, res, next) => {
  try {
    const messageIdParam = Number(req.params.id);
    if (!messageIdParam) {
      return res.status(400).json({ detail: "Invalid message ID" });
    }

    const msg = await one(
      `SELECT m.id, conv.session_id
       FROM qr_message m
       JOIN qr_conversation conv ON m.conversation_id = conv.id
       WHERE m.id = $1`,
      [messageIdParam]
    );

    if (!msg) {
      return res.status(404).json({ detail: "Message not found" });
    }

    const allowed = await mayUseSession(req.identity, Number(msg.session_id));
    if (!allowed) {
      return res.status(403).json({ detail: "Forbidden: session access denied" });
    }

    const starredState = req.body?.starred !== false; // Default true if omitted

    const updated = await one(
      `UPDATE qr_message
       SET starred = $1
       WHERE id = $2
       RETURNING id, starred`,
      [starredState, messageIdParam]
    );

    res.json({ id: Number(updated.id), starred: Boolean(updated.starred) });
  } catch (err) {
    next(err);
  }
});

export default router;
