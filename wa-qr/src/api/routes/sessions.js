/**
 * REST API Routes: Sessions Management
 */

import express from "express";
import * as manager from "../../sessions/manager.js";

const router = express.Router();

// GET /api/sessions
router.get("/", async (req, res, next) => {
  try {
    const list = await manager.listSessions();
    res.json(list);
  } catch (err) {
    next(err);
  }
});

// POST /api/sessions
router.post("/", async (req, res, next) => {
  try {
    const { label } = req.body || {};
    const created = await manager.createSession({ label });
    res.status(201).json(created);
  } catch (err) {
    next(err);
  }
});

// DELETE /api/sessions/:id
router.delete("/:id", async (req, res, next) => {
  try {
    await manager.destroySession(req.params.id);
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});

// GET /api/sessions/:id/qr
router.get("/:id/qr", async (req, res, next) => {
  try {
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

export default router;
