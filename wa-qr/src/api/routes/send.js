/**
 * REST API Routes: Outbound Sending
 */

import express from "express";
import { sendOutboundMessage } from "../../outbound/send.js";

const router = express.Router();

// POST /api/send
router.post("/", async (req, res, next) => {
  try {
    const result = await sendOutboundMessage(req.body || {});
    res.status(201).json(result);
  } catch (err) {
    res.status(400).json({ detail: err.message });
  }
});

export default router;
