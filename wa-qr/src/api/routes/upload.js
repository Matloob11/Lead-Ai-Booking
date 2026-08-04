/**
 * REST API Routes: Media File Upload
 *
 * Accepts multipart file upload, enforces maxMediaBytes size cap, sanitizes filename,
 * and saves bytes to DATA_ROOT/media/YYYY-MM/<sha12>_<safe-name>.
 */

import express from "express";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import Busboy from "busboy";

import { config, mediaRoot } from "../../config.js";
import { mayUseSession } from "../identity.js";

const router = express.Router();

// POST /api/upload?session_id=
router.post("/", async (req, res, next) => {
  try {
    const sessionId = req.query.session_id
      ? Number(req.query.session_id)
      : req.body?.session_id
        ? Number(req.body.session_id)
        : null;

    // Required, not optional. Written as `if (sessionId)` this read like a
    // permission check and was one only for callers who chose to be checked:
    // leaving session_id off skipped it entirely, and any agent — including one
    // holding no phone at all — could write files onto the server's disk.
    if (!sessionId) {
      return res.status(400).json({ detail: "session_id is required" });
    }
    if (!(await mayUseSession(req.identity, sessionId))) {
      return res.status(403).json({ detail: "That number is not assigned to you." });
    }

    const contentType = req.headers["content-type"] || "";
    if (!contentType.includes("multipart/form-data")) {
      return res.status(400).json({ detail: "Content-Type must be multipart/form-data" });
    }

    const bb = Busboy({
      headers: req.headers,
      limits: {
        fileSize: config.maxMediaBytes,
        files: 1,
      },
    });

    let uploadedResult = null;
    let fileTooLarge = false;
    let fileError = null;
    const filePromises = [];

    bb.on("file", (_fieldname, fileStream, info, _encoding, mimetype) => {
      let filename = "";
      let mimeType = "";
      if (typeof info === "object" && info !== null) {
        filename = info.filename;
        mimeType = info.mimeType || info.mimetype;
      } else if (typeof info === "string") {
        filename = info;
        mimeType = mimetype;
      }

      // Sanitize filename to prevent path traversal and shell injection
      const baseName = path.basename(filename || "attachment.bin");
      const safeName = baseName.replace(/[^\w.-]+/g, "_").slice(0, 100) || "attachment.bin";

      const now = new Date();
      const yearMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
      const targetDir = path.join(mediaRoot, yearMonth);

      try {
        fs.mkdirSync(targetDir, { recursive: true });
      } catch (err) {
        fileError = err;
        fileStream.resume();
        return;
      }

      const hexPrefix = crypto.randomBytes(6).toString("hex"); // 12 hex characters
      const diskFileName = `${hexPrefix}_${safeName}`;
      const absolutePath = path.join(targetDir, diskFileName);
      const relativePath = path.join(yearMonth, diskFileName).replace(/\\/g, "/");

      const writeStream = fs.createWriteStream(absolutePath);
      let sizeBytes = 0;

      fileStream.on("data", (chunk) => {
        sizeBytes += chunk.length;
      });

      fileStream.on("limit", () => {
        fileTooLarge = true;
        writeStream.destroy();
        fs.unlink(absolutePath, () => {});
      });

      fileStream.on("error", (err) => {
        fileError = err;
        fs.unlink(absolutePath, () => {});
      });

      fileStream.pipe(writeStream);

      const promise = new Promise((resolve) => {
        writeStream.on("finish", () => {
          if (!fileTooLarge && !fileError) {
            uploadedResult = {
              media_path: relativePath,
              mime_type: mimeType || "application/octet-stream",
              file_name: safeName,
              size_bytes: sizeBytes,
            };
          }
          resolve();
        });
        writeStream.on("error", () => resolve());
      });

      filePromises.push(promise);
    });

    bb.on("error", (err) => {
      next(err);
    });

    bb.on("finish", async () => {
      try {
        await Promise.all(filePromises);

        if (fileTooLarge) {
          return res
            .status(400)
            .json({ detail: `File size exceeds maximum limit of ${config.maxMediaBytes} bytes` });
        }
        if (fileError) {
          return res.status(500).json({ detail: `File upload error: ${fileError.message}` });
        }
        if (!uploadedResult) {
          return res.status(400).json({ detail: "No file was attached in the multipart request" });
        }

        res.status(201).json(uploadedResult);
      } catch (err) {
        next(err);
      }
    });

    req.pipe(bb);
  } catch (err) {
    next(err);
  }
});

export default router;
