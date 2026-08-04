import express from "express";
import { mayUseSession } from "../identity.js";
import { getClient } from "../../sessions/manager.js";
import { one } from "../../db.js";

const router = express.Router();

/**
 * Timeout wrapper for page evaluations (15s deadline).
 */
function withTimeout(promise, ms, description) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(
        () => reject(new Error(`${description} timed out after ${ms / 1000}s`)),
        ms
      );
    }),
  ]).finally(() => clearTimeout(timer));
}

/**
 * GET /api/contacts/:wa_id?session_id=
 * Retrieves contact details (profile picture URL, pushname, about, isBusiness).
 * Each Puppeteer/page evaluation is protected by a 15-second timeout and try/catch blocks.
 */
router.get("/:wa_id", async (req, res, next) => {
  try {
    const sessionId = Number(req.query.session_id);
    if (!sessionId) {
      return res.status(400).json({ detail: "session_id parameter is required" });
    }

    if (!(await mayUseSession(req.identity, sessionId))) {
      return res.status(403).json({ detail: "Forbidden: session access denied" });
    }

    const rawWaId = req.params.wa_id || "";
    const digits = rawWaId.replace(/\D/g, "");
    if (!digits) {
      return res.status(400).json({ detail: "Invalid wa_id" });
    }

    const formattedWaId = rawWaId.includes("@") ? rawWaId : `${digits}@c.us`;
    const client = getClient(sessionId);

    if (!client) {
      return res.status(530).json({ detail: `Session ${sessionId} is not connected` });
    }

    let profilePicUrl = null;
    let pushname = "";
    let about = null;
    let isBusiness = false;

    // 1. Profile Picture URL with 15s timeout
    try {
      profilePicUrl = await withTimeout(
        client.getProfilePicUrl(formattedWaId),
        15000,
        "getProfilePicUrl"
      ).catch(() => null);
    } catch (err) {
      console.warn(`[wa-qr] profile pic fetch error for ${digits}: ${err.message}`);
    }

    // 2. Contact details & About with 15s timeout
    try {
      const contact = await withTimeout(
        client.getContactById(formattedWaId),
        15000,
        "getContactById"
      ).catch(() => null);

      if (contact) {
        pushname = contact.pushname || contact.name || contact.shortName || "";
        isBusiness = Boolean(contact.isBusiness);

        if (typeof contact.getAbout === "function") {
          try {
            about = await withTimeout(contact.getAbout(), 15000, "getAbout").catch(() => null);
          } catch (e) {
            about = null;
          }
        }
      }
    } catch (err) {
      console.warn(`[wa-qr] contact info error for ${digits}: ${err.message}`);
    }

    // DB fallback if pushname is empty
    if (!pushname) {
      const dbContact = await one(
        `SELECT profile_name, display_name FROM qr_contact WHERE wa_id = $1`,
        [digits]
      );
      if (dbContact) {
        pushname = dbContact.profile_name || dbContact.display_name || "";
      }
    }

    return res.json({
      wa_id: digits,
      formatted_id: formattedWaId,
      profile_pic_url: profilePicUrl,
      pushname: pushname || null,
      about: about || null,
      is_business: isBusiness,
    });
  } catch (err) {
    next(err);
  }
});

export default router;
