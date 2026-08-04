/**
 * REST API Routes: Outbound Sending
 */

import express from "express";
import { sendOutboundMessage } from "../../outbound/send.js";
import { mayUseSession } from "../identity.js";

const router = express.Router();

// POST /api/send
router.post("/", async (req, res, next) => {
  try {
    // Sending is the one action a customer sees. A message that goes out over
    // somebody else's number is not a leak that can be taken back.
    if (!(await mayUseSession(req.identity, req.body?.session_id))) {
      return res.status(403).json({ detail: "That number is not assigned to you." });
    }

    const result = await sendOutboundMessage(req.body || {});
    res.status(201).json(result);
  } catch (err) {
    res.status(400).json({ detail: err.message });
  }
});

export default router;
