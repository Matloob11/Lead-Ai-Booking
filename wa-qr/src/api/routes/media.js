/**
 * REST API Routes: Media File Serving
 */

import express from "express";
import path from "node:path";
import { mediaRoot } from "../../config.js";
import { one } from "../../db.js";

const router = express.Router();

// GET /api/media/:id
router.get("/:id", async (req, res, next) => {
  try {
    const mediaId = Number(req.params.id);
    const row = await one(`SELECT * FROM qr_media WHERE id = $1`, [mediaId]);

    if (!row || !row.downloaded || !row.file_path) {
      return res.status(404).json({ detail: "Media file not found or not downloaded" });
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
