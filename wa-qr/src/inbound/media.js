/**
 * Media Download and Processing for Inbound Messages
 */

import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { config, mediaRoot } from "../config.js";
import { one } from "../db.js";

export async function processInboundMedia(message) {
  if (!message || !message.hasMedia) return null;

  try {
    const media = await message.downloadMedia().catch((err) => {
      throw new Error(`downloadMedia failed: ${err.message}`);
    });

    if (!media || !media.data) {
      const row = await one(
        `INSERT INTO qr_media (downloaded, download_error) VALUES (false, 'No media data returned') RETURNING *`
      );
      return { id: Number(row.id), downloaded: false, download_error: row.download_error };
    }

    const buffer = Buffer.from(media.data, "base64");
    const sizeBytes = buffer.length;
    const fileName = media.filename || `${message.type || "file"}_${Date.now()}`;

    // Max size check
    if (sizeBytes > config.maxMediaBytes) {
      const errorMsg = `Media size (${(sizeBytes / 1024 / 1024).toFixed(1)}MB) exceeds max limit (${(config.maxMediaBytes / 1024 / 1024).toFixed(0)}MB)`;
      const row = await one(
        `INSERT INTO qr_media (mime_type, file_name, size_bytes, downloaded, download_error)
         VALUES ($1, $2, $3, false, $4) RETURNING *`,
        [media.mimetype || "", fileName, sizeBytes, errorMsg]
      );
      return { id: Number(row.id), downloaded: false, download_error: errorMsg };
    }

    const sha256 = crypto.createHash("sha256").update(buffer).digest("hex");
    const now = new Date();
    const yearMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const targetDir = path.join(mediaRoot, yearMonth);
    await fs.mkdir(targetDir, { recursive: true });

    const safeFileName = fileName.replace(/[^\w.-]+/g, "_");
    const relativePath = path.join(yearMonth, `${sha256.slice(0, 12)}_${safeFileName}`);
    const absolutePath = path.join(mediaRoot, relativePath);

    await fs.writeFile(absolutePath, buffer);

    const row = await one(
      `INSERT INTO qr_media (file_path, mime_type, file_name, size_bytes, sha256, downloaded)
       VALUES ($1, $2, $3, $4, $5, true) RETURNING *`,
      [relativePath, media.mimetype || "", fileName, sizeBytes, sha256]
    );

    const mediaId = Number(row.id);
    return {
      id: mediaId,
      mimetype: media.mimetype || "",
      filename: fileName,
      sha256,
      size_bytes: sizeBytes,
      downloaded: true,
      filelink: `/api/media/${mediaId}`,
    };
  } catch (err) {
    const errorMsg = err.message || "Failed to download media";
    const row = await one(
      `INSERT INTO qr_media (downloaded, download_error) VALUES (false, $1) RETURNING *`,
      [errorMsg]
    );
    return { id: Number(row.id), downloaded: false, download_error: errorMsg };
  }
}
