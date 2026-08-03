/**
 * Event Persistence and DB Synchronisation
 */

import { onEvent } from "../sessions/manager.js";
import * as store from "../sessions/store.js";
import {
  toWaId,
  kindOf,
  inboundMessage,
  inboundReaction,
  statusUpdate,
} from "./normalise.js";
import { processInboundMedia } from "./media.js";
import { emitWebhook } from "../webhook/emit.js";
import { q, one } from "../db.js";

/** Subscribes to events from session manager and processes them. */
export function startPersistence() {
  onEvent(handleEvent);
  console.info("[wa-qr] inbound persistence active");
}

async function handleEvent(type, payload) {
  try {
    if (type === "status") {
      console.info(
        `[wa-qr] session #${payload.sessionId} status changed: ${payload.status} ${payload.error ? `(${payload.error})` : ""}`
      );
      return;
    }

    if (type === "message") {
      await processMessageEvent(payload.sessionId, payload.message);
    } else if (type === "reaction") {
      await processReactionEvent(payload.sessionId, payload.reaction);
    } else if (type === "ack") {
      await processAckEvent(payload.sessionId, payload.message, payload.ack);
    }
  } catch (err) {
    console.error(`[wa-qr] error handling event ${type}:`, err);
  }
}

async function processMessageEvent(sessionId, message) {
  if (!message) return;

  const wamid = message.id?._serialized || String(message.id || "");
  if (!wamid) return;

  // Insert raw event record first
  const eventRow = await one(
    `INSERT INTO qr_event (session_id, kind, payload, status)
     VALUES ($1, 'message', $2, 'pending') RETURNING *`,
    [sessionId, message.rawData || message._data || {}]
  );

  const session = await store.getSessionById(sessionId);
  const phoneNumber = store.visibleNumber(session);

  // Process media if present
  const mediaRecord = message.hasMedia ? await processInboundMedia(message) : null;

  // Fetch contact info
  let contactName = "";
  try {
    const contact = await message.getContact();
    contactName = contact.name || contact.pushname || "";
  } catch {}

  // Generate normalized Meta payload
  const metaPayload = inboundMessage(message, { contactName, media: mediaRecord });

  const direction = message.fromMe ? "out" : "in";
  const kind = kindOf(message);
  const body = message.body || "";
  const isGroup = Boolean(message.from?.endsWith("@g.us"));
  const authorWaId = isGroup ? toWaId(message.author || message.from) : "";
  const contactWaId = isGroup
    ? toWaId(message.from)
    : direction === "in"
      ? toWaId(message.from)
      : toWaId(message.to);

  // Quote lookup
  let replyToId = null;
  if (message.hasQuotedMsg && message._quotedId) {
    const parent = await one(`SELECT id FROM qr_message WHERE wamid = $1`, [
      message._quotedId,
    ]);
    if (parent) replyToId = Number(parent.id);
  }

  // 1. Contact row
  const contactRow = await one(
    `INSERT INTO qr_contact (wa_id, profile_name, display_name)
     VALUES ($1, $2, $2)
     ON CONFLICT (wa_id) DO UPDATE SET
       profile_name = EXCLUDED.profile_name,
       display_name = COALESCE(NULLIF(qr_contact.display_name, ''), EXCLUDED.profile_name)
     RETURNING id`,
    [contactWaId, contactName]
  );
  const contactId = Number(contactRow.id);

  // 2. Conversation row
  const conversationRow = await one(
    `INSERT INTO qr_conversation (session_id, contact_id, is_group, subject, last_message_at, last_message_preview, last_message_kind, unread_count)
     VALUES ($1, $2, $3, $4, now(), $5, $6, $7)
     ON CONFLICT (session_id, contact_id) DO UPDATE SET
       last_message_at = now(),
       last_message_preview = EXCLUDED.last_message_preview,
       last_message_kind = EXCLUDED.last_message_kind,
       unread_count = CASE WHEN $8 = 'in' THEN qr_conversation.unread_count + 1 ELSE qr_conversation.unread_count END
     RETURNING id`,
    [
      sessionId,
      contactId,
      isGroup,
      isGroup ? contactName : "",
      body.slice(0, 200),
      kind,
      direction === "in" ? 1 : 0,
      direction,
    ]
  );
  const conversationId = Number(conversationRow.id);

  // 3. Message row with ON CONFLICT (wamid) DO NOTHING
  const initialStatus = direction === "in" ? "received" : message.ack ? statusUpdate(message, message.ack).statuses[0].status : "sent";

  await q(
    `INSERT INTO qr_message (conversation_id, direction, kind, wamid, body, media_id, reply_to_id, author_wa_id, status, payload)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
     ON CONFLICT (wamid) DO NOTHING`,
    [
      conversationId,
      direction,
      kind,
      wamid,
      body,
      mediaRecord?.id || null,
      replyToId,
      authorWaId,
      initialStatus,
      metaPayload,
    ]
  );

  // 4. Mark event processed and emit webhook
  await q(`UPDATE qr_event SET status = 'processed' WHERE id = $1`, [eventRow.id]);
  await emitWebhook(eventRow.id, metaPayload, phoneNumber);
}

async function processReactionEvent(sessionId, reaction) {
  if (!reaction) return;

  const eventRow = await one(
    `INSERT INTO qr_event (session_id, kind, payload, status)
     VALUES ($1, 'reaction', $2, 'pending') RETURNING *`,
    [sessionId, reaction]
  );

  const session = await store.getSessionById(sessionId);
  const phoneNumber = store.visibleNumber(session);
  const metaPayload = inboundReaction(reaction);

  const targetWamid = reaction.msgId?._serialized || String(reaction.msgId || "");
  const senderWaId = toWaId(reaction.senderId);
  const emoji = reaction.reaction || "";

  if (targetWamid) {
    const msgRow = await one(`SELECT id, reactions FROM qr_message WHERE wamid = $1`, [
      targetWamid,
    ]);
    if (msgRow) {
      let reactionsMap = msgRow.reactions || {};
      if (typeof reactionsMap !== "object") reactionsMap = {};

      if (emoji) {
        reactionsMap[senderWaId] = emoji;
      } else {
        delete reactionsMap[senderWaId];
      }

      await q(`UPDATE qr_message SET reactions = $1 WHERE id = $2`, [
        JSON.stringify(reactionsMap),
        msgRow.id,
      ]);
    }
  }

  await q(`UPDATE qr_event SET status = 'processed' WHERE id = $1`, [eventRow.id]);
  await emitWebhook(eventRow.id, metaPayload, phoneNumber);
}

async function processAckEvent(sessionId, message, ack) {
  if (!message) return;

  const eventRow = await one(
    `INSERT INTO qr_event (session_id, kind, payload, status)
     VALUES ($1, 'ack', $2, 'pending') RETURNING *`,
    [sessionId, { ack, wamid: message.id?._serialized }]
  );

  const session = await store.getSessionById(sessionId);
  const phoneNumber = store.visibleNumber(session);
  const metaPayload = statusUpdate(message, ack);

  const targetWamid = message.id?._serialized || String(message.id || "");
  const statusStr = metaPayload.statuses[0]?.status || "sent";

  if (targetWamid) {
    await q(
      `UPDATE qr_message
       SET status = $1,
           delivered_at = CASE WHEN $1 = 'delivered' AND delivered_at IS NULL THEN now() ELSE delivered_at END,
           read_at = CASE WHEN $1 = 'read' AND read_at IS NULL THEN now() ELSE read_at END
       WHERE wamid = $2`,
      [statusStr, targetWamid]
    );
  }

  await q(`UPDATE qr_event SET status = 'processed' WHERE id = $1`, [eventRow.id]);
  await emitWebhook(eventRow.id, metaPayload, phoneNumber);
}

// Automatically start persistence when imported
startPersistence();
