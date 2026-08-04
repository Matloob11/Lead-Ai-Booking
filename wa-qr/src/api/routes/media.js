/**
 * REST API Routes: Media File Serving
 */

import express from "express";
import path from "node:path";
import { mediaRoot } from "../../config.js";
import { one } from "../../db.js";
import { visibleSessionIds } from "../identity.js";

const router = express.Router();

/**
 * The types that may be served as themselves, so a browser will render them.
 *
 * An allowlist and never a denylist. Everything here arrived from outside the
 * company, and the whole reason the download route flattens files to
 * application/octet-stream is that serving a stranger's upload under its own
 * declared type is how an SVG full of script, or an HTML file named .jpg,
 * becomes a page running on this origin.
 *
 * These are formats a browser decodes rather than executes. image/svg+xml is
 * deliberately absent: it is a document that can carry script, not a picture.
 */
const INLINE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
  "image/bmp",
  "audio/ogg",
  "audio/mpeg",
  "audio/mp4",
  "audio/aac",
  "audio/wav",
  "audio/webm",
  "video/mp4",
  "video/webm",
  "video/3gpp",
  "video/quicktime",
]);

/** The row, if this caller is allowed it and its bytes are actually on disk. */
async function reachableMedia(req, mediaId) {
  const row = await one(`SELECT * FROM qr_media WHERE id = $1`, [mediaId]);
  if (!row || !row.downloaded || !row.file_path) return null;

  // An attachment belongs to the phone whose thread it arrived on. Ids here
  // count up just like conversation ids do, so without this check the photo a
  // customer sent one agent is readable by every other agent in the building.
  const allowed = await visibleSessionIds(req.identity);
  if (allowed === null) return row;

  const owner = await one(
    `SELECT conv.session_id
       FROM qr_message m
       JOIN qr_conversation conv ON m.conversation_id = conv.id
      WHERE m.media_id = $1
      LIMIT 1`,
    [mediaId]
  );
  return owner && allowed.includes(Number(owner.session_id)) ? row : null;
}

/**
 * GET /api/media/:id/inline — the same bytes, shown rather than downloaded.
 *
 * The download route below hands every file over as application/octet-stream
 * with nosniff, which is the right thing for a document and fatal for a
 * photograph: nosniff is precisely the instruction not to work out that those
 * bytes are a JPEG, so an <img> pointing at it renders nothing. Every picture
 * on this screen was a broken image icon.
 *
 * So the type is declared honestly here, and only for the handful of formats a
 * browser decodes rather than executes. Anything else keeps its old answer —
 * a download — because for those the flattening is the protection.
 */
router.get("/:id/inline", async (req, res, next) => {
  try {
    const mediaId = Number(req.params.id);
    const row = await reachableMedia(req, mediaId);
    if (!row) return res.status(404).json({ detail: "Media file not found" });

    const mime = String(row.mime_type || "").split(";")[0].trim().toLowerCase();
    if (!INLINE_TYPES.has(mime)) {
      // Not a refusal so much as a redirection to the route that can serve it.
      return res.redirect(302, `../${mediaId}`);
    }

    res.setHeader("Content-Type", mime);
    res.setHeader("Content-Disposition", "inline");
    // Still nosniff: it now means "this really is what I said it is", which is
    // the guarantee worth keeping once the type is no longer a lie.
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Cross-Origin-Resource-Policy", "same-site");
    res.setHeader("Cache-Control", "private, max-age=86400");

    res.sendFile(path.join(mediaRoot, row.file_path), (err) => {
      if (err && !res.headersSent) res.status(404).json({ detail: "File on disk missing" });
    });
  } catch (err) {
    next(err);
  }
});

// GET /api/media/:id
router.get("/:id", async (req, res, next) => {
  try {
    const mediaId = Number(req.params.id);
    const row = await reachableMedia(req, mediaId);

    if (!row) {
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
