/**
 * REST API Routes: Media File Serving
 */

import express from "express";
import path from "node:path";
import { mediaRoot } from "../../config.js";
import { one } from "../../db.js";
import { visibleSessionIds } from "../identity.js";

const router = express.Router();

// GET /api/media/:id
router.get("/:id", async (req, res, next) => {
  try {
    const mediaId = Number(req.params.id);
    const row = await one(`SELECT * FROM qr_media WHERE id = $1`, [mediaId]);

    if (!row || !row.downloaded || !row.file_path) {
      return res.status(404).json({ detail: "Media file not found or not downloaded" });
    }

    // An attachment belongs to the phone whose thread it arrived on. Ids here
    // count up just like conversation ids do, so without this check the photo a
    // customer sent one agent is readable by every other agent in the building.
    const allowed = await visibleSessionIds(req.identity);
    if (allowed !== null) {
      const owner = await one(
        `SELECT conv.session_id
           FROM qr_message m
           JOIN qr_conversation conv ON m.conversation_id = conv.id
          WHERE m.media_id = $1
          LIMIT 1`,
        [mediaId]
      );
      if (!owner || !allowed.includes(Number(owner.session_id))) {
        return res.status(404).json({ detail: "Media file not found or not downloaded" });
      }
    }

    const absolutePath = path.join(mediaRoot, row.file_path);

    // SECURITY COMPLIANCE: Forces browser download as attachment
    res.setHeader("Content-Type", "application/octet-stream");
    res.setHeader(
      "Content-Disposition",
      `attachment; filename="${row.file_name.replace(/[^\w.-]+/g, "_") || "attachment"}"`
    );
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Content-Security-Policy", "sandbox; default-src 'none'");

    res.sendFile(absolutePath, (err) => {
      if (err && !res.headersSent) {
        res.status(404).json({ detail: "File on disk missing" });
      }
    });
  } catch (err) {
    next(err);
  }
});

export default router;
