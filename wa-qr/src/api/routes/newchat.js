import express from "express";
import { mayUseSession } from "../identity.js";
import { getClient } from "../../sessions/manager.js";
import { guardNumber } from "../../config.js";
import { sendOutboundMessage } from "../../outbound/send.js";
import { getSessionRisk } from "../../outbound/risk_eval.js";
// The limits are not imported here on purpose — they live inside
// sendOutboundMessage, which is the one door every outbound message goes
// through. Calling them from this route as well would apply each one twice.
import { one } from "../../db.js";

const router = express.Router();

/**
 * GET /api/newchat/check?session_id=&phone=
 * Checks if a phone number exists on WhatsApp, is guarded, whether a conversation exists,
 * and includes current session risk assessment WITHOUT sending any message.
 */
router.get("/check", async (req, res, next) => {
  try {
    const sessionId = Number(req.query.session_id);
    const rawPhone = req.query.phone || "";

    if (!sessionId) {
      return res.status(400).json({ detail: "session_id parameter is required" });
    }
    if (!(await mayUseSession(req.identity, sessionId))) {
      return res.status(403).json({ detail: "Forbidden: session access denied" });
    }

    const digits = String(rawPhone).replace(/\D/g, "");
    if (!digits) {
      return res.status(400).json({ detail: "A valid phone number is required" });
    }

    // 1. Guard check for 21 Platform numbers
    let isGuarded = false;
    try {
      guardNumber(digits);
    } catch (err) {
      isGuarded = true;
    }

    // 2. Risk assessment
    const risk = await getSessionRisk(sessionId);

    // 3. Client getNumberId check
    const client = getClient(sessionId);
    let existsOnWhatsapp = false;
    if (client && !isGuarded) {
      try {
        const wid = await client.getNumberId(digits);
        existsOnWhatsapp = Boolean(wid);
      } catch (err) {
        existsOnWhatsapp = false;
      }
    }

    // 4. Is there already a thread with this person?
    //
    // Read only. This used to create the contact if it did not find one, which
    // meant a route called "check" wrote a row — and the panel calls it while
    // somebody is still typing, so the contact list filled up with 9, 97, 971,
    // 9715 and every other half-finished number on the way to a real one.
    const convRow = await one(
      `SELECT conv.id
         FROM qr_conversation conv
         JOIN qr_contact c ON c.id = conv.contact_id
        WHERE conv.session_id = $1 AND c.wa_id = $2`,
      [sessionId, digits]
    );
    const existingConversationId = convRow ? Number(convRow.id) : null;

    return res.json({
      session_id: sessionId,
      phone: digits,
      exists_on_whatsapp: existsOnWhatsapp,
      guarded: isGuarded,
      existing_conversation_id: existingConversationId,
      risk,
    });
  } catch (err) {
    next(err);
  }
});

/**
 * POST /api/newchat { session_id, phone, first_message }
 * Initiates a chat with a new contact. Enforces E.164 normalization, getNumberId pre-check,
 * Business Platform number guarding, high-risk blocking (409), rate limits, bulk duplicate guard,
 * pacing delay, and existing conversation reuse.
 */
router.post("/", async (req, res, next) => {
  try {
    const { session_id, phone, first_message } = req.body || {};
    const sessionId = Number(session_id);

    if (!sessionId) {
      return res.status(400).json({ detail: "session_id is required" });
    }
    if (!(await mayUseSession(req.identity, sessionId))) {
      return res.status(403).json({ detail: "Forbidden: session access denied" });
    }

    const digits = String(phone || "").replace(/\D/g, "");
    if (!digits) {
      return res.status(400).json({ detail: "Valid phone number is required" });
    }
    if (!first_message || typeof first_message !== "string" || !first_message.trim()) {
      return res.status(400).json({ detail: "first_message is required" });
    }

    // 1. Guard check for 21 Business Platform numbers
    try {
      guardNumber(digits);
    } catch (err) {
      return res.status(400).json({
        detail: `+${digits} is live on WhatsApp Business Platform and must not be linked or messaged by QR.`,
      });
    }

    // 2. getNumberId pre-check (BEFORE sending any message)
    const client = getClient(sessionId);
    if (!client) {
      return res.status(503).json({ detail: `Session ${sessionId} is not ready or connected` });
    }

    let wid = null;
    try {
      wid = await client.getNumberId(digits);
    } catch (err) {
      console.warn(`[wa-qr] getNumberId failed for ${digits}: ${err.message}`);
    }

    if (!wid) {
      return res.status(404).json({
        detail: `+${digits} is not on WhatsApp.`,
      });
    }

    // The number as typed, not `wid.user`.
    //
    // getNumberId answers with WhatsApp's own addressing, and on this account
    // that is often a LinkedID — `140879440429235` for a UAE mobile. Passing
    // that on as the recipient made the send resolve it back to a phone number
    // internally while everything here went on believing the LinkedID was the
    // number, so the conversation this route had just created could not be
    // found again and it answered `conversation_id: null`.
    //
    // sendOutboundMessage does its own resolution either way, so the honest
    // thing to hand it is what the person actually typed.
    const recipientWaId = digits;

    // 3. Safety Check: Session Risk Level
    const risk = await getSessionRisk(sessionId);
    if (risk.level === "high") {
      return res.status(409).json({
        detail:
          "Session risk level is HIGH. Starting new conversations on high-risk numbers is blocked to prevent WhatsApp account ban.",
        reasons: risk.reasons,
        risk,
      });
    }

    // 4. Send it.
    //
    // The contact and the conversation are not created here. They were, with
    // hand-written SQL naming a `name` column on qr_contact and an `updated_at`
    // on both tables — none of which exist, so this route threw the moment it
    // was pointed at a number it had not seen before, which is its only job.
    // sendOutboundMessage already does both upserts, correctly, and it is also
    // where the daily cap, the bulk guard and the pause now live — so they
    // cannot be walked past by sending to a new number through /api/send.
    const sendResult = await sendOutboundMessage({
      session_id: sessionId,
      to: recipientWaId,
      body: first_message,
    });

    const convRow = await one(
      `SELECT conv.id
         FROM qr_conversation conv
         JOIN qr_contact c ON c.id = conv.contact_id
        WHERE conv.session_id = $1 AND c.wa_id = $2`,
      [sessionId, recipientWaId]
    );

    return res.status(201).json({
      conversation_id: convRow ? Number(convRow.id) : null,
      message: sendResult,
      contact: {
        wa_id: recipientWaId,
      },
      risk,
    });
  } catch (err) {
    next(err);
  }
});

export default router;
