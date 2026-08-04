/**
 * REST API Routes: Outbound Actions
 *
 * Implements endpoints for reactions, read receipts (seen), typing indicators,
 * message forwarding, and delete for everyone.
 */

import express from "express";
import {
  reactToMessage,
  markChatSeen,
  setTyping,
  forwardMessage,
  deleteForEveryone,
} from "../../outbound/actions.js";
import { mayUseSession } from "../identity.js";
import { one } from "../../db.js";

const router = express.Router();

// Helper to check session access and throw 403
async function checkSessionAccess(req, sessionId) {
  if (!sessionId) return;
  const allowed = await mayUseSession(req.identity, sessionId);
  if (!allowed) {
    const err = new Error("Forbidden: session access denied");
    err.status = 403;
    throw err;
  }
}

// POST /api/actions/react
router.post("/react", async (req, res, next) => {
  try {
    const { session_id, wamid, emoji } = req.body || {};
    await checkSessionAccess(req, session_id);

    const result = await reactToMessage({ session_id, wamid, emoji });
    res.json(result);
  } catch (err) {
    next(err);
  }
});

// POST /api/actions/seen
router.post("/seen", async (req, res, next) => {
  try {
    const { session_id, conversation_id } = req.body || {};
    let sessionId = session_id ? Number(session_id) : null;

    if (!sessionId && conversation_id) {
      const conv = await one(`SELECT session_id FROM qr_conversation WHERE id = $1`, [
        conversation_id,
      ]);
      if (conv) sessionId = Number(conv.session_id);
    }

    await checkSessionAccess(req, sessionId);

    const result = await markChatSeen({ session_id: sessionId, conversation_id });
    res.json(result);
  } catch (err) {
    next(err);
  }
});

// POST /api/actions/typing
router.post("/typing", async (req, res, next) => {
  try {
    const { session_id, conversation_id, typing } = req.body || {};
    let sessionId = session_id ? Number(session_id) : null;

    if (!sessionId && conversation_id) {
      const conv = await one(`SELECT session_id FROM qr_conversation WHERE id = $1`, [
        conversation_id,
      ]);
      if (conv) sessionId = Number(conv.session_id);
    }

    await checkSessionAccess(req, sessionId);

    const result = await setTyping({ session_id: sessionId, conversation_id, typing });
    res.json(result);
  } catch (err) {
    next(err);
  }
});

// POST /api/actions/forward
router.post("/forward", async (req, res, next) => {
  try {
    const { session_id, wamid, to_wa_id } = req.body || {};
    await checkSessionAccess(req, session_id);

    const result = await forwardMessage({ session_id, wamid, to_wa_id });
    res.json(result);
  } catch (err) {
    next(err);
  }
});

// POST /api/actions/delete
router.post("/delete", async (req, res, next) => {
  try {
    const { session_id, wamid } = req.body || {};
    let sessionId = session_id ? Number(session_id) : null;

    if (!sessionId && wamid) {
      const msg = await one(
        `SELECT conv.session_id
         FROM qr_message m
         JOIN qr_conversation conv ON m.conversation_id = conv.id
         WHERE m.wamid = $1`,
        [wamid]
      );
      if (msg) sessionId = Number(msg.session_id);
    }

    await checkSessionAccess(req, sessionId);

    const result = await deleteForEveryone({ session_id: sessionId, wamid });
    res.json(result);
  } catch (err) {
    next(err);
  }
});

export default router;
