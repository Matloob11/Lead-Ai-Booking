/**
 * Event Persistence and DB Synchronisation
 */

import { onEvent, getClient } from "../sessions/manager.js";
import * as store from "../sessions/store.js";
import {
  toWaId,
  resolveContactWaId,
  kindOf,
  inboundMessage,
  inboundReaction,
  statusUpdate,
} from "./normalise.js";
import { processInboundMedia } from "./media.js";
import { emitWebhook } from "../webhook/emit.js";
import { config } from "../config.js";
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

  const fromJid = message.from || "";
  const toJid = message.to || "";
  const remoteJid = message.id?.remote || "";

  // Filter out Broadcasts, Statuses, Newsletters
  if (
    fromJid.includes("status@broadcast") ||
    toJid.includes("status@broadcast") ||
    remoteJid.includes("status@broadcast") ||
    fromJid.endsWith("@newsletter") ||
    toJid.endsWith("@newsletter") ||
    fromJid.endsWith("@broadcast") ||
    toJid.endsWith("@broadcast")
  ) {
    console.info(`[wa-qr] Ignoring status/newsletter/broadcast message event (${fromJid || remoteJid})`);
    return;
  }

  // Groups, when they are not wanted — checked on both ends because an
  // outbound message to a group carries the group in `to`, not in `from`.
  // Dropped here rather than hidden later: the phone belongs to a person and
  // brings their family and neighbourhood threads with it, and none of that is
  // the company's to store.
  if (
    config.ignoreGroups &&
    (fromJid.endsWith("@g.us") || toJid.endsWith("@g.us") || remoteJid.endsWith("@g.us"))
  ) {
    return;
  }

  const client = getClient(sessionId);

  // Fetch contact info & resolve wa_id
  let contactName = "";
  try {
    const contact = await message.getContact();
    contactName = contact.name || contact.pushname || "";
  } catch {}

  const direction = message.fromMe ? "out" : "in";
  const kind = kindOf(message);
  const body = message.body || "";
  const isGroup = Boolean(message.from?.endsWith("@g.us"));
  const rawTargetJid = isGroup
    ? message.from
    : direction === "in"
      ? message.from
      : message.to;

  const resolvedContact = await resolveContactWaId({ client, jid: rawTargetJid, message });
  const contactWaId = resolvedContact.waId;

  if (!contactWaId) {
    console.warn(`[wa-qr] Could not resolve valid contact wa_id for JID ${rawTargetJid}, skipping message persistence.`);
    return;
  }

  let authorWaId = "";
  if (isGroup && (message.author || message.from)) {
    const resolvedAuthor = await resolveContactWaId({ client, jid: message.author || message.from, message });
    authorWaId = resolvedAuthor.waId;
  }

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

  // Which message this one answers, if any.
  let quotedId = "";
  if (message.hasQuotedMsg) {
    try {
      const quoted = await message.getQuotedMessage();
      quotedId = quoted?.id?._serialized || "";
    } catch (err) {
      console.warn("[wa-qr] could not read the quoted message:", err.message);
    }
  }

  // Generate normalized Meta payload
  const metaPayload = inboundMessage(message, {
    contactName,
    media: mediaRecord,
    quotedId,
    waId: contactWaId,
  });

  // A miss here is normal: the quoted message may predate this session, in
  // which case the reply is stored without being joined to what it answers.
  let replyToId = null;
  if (quotedId) {
    const parent = await one(`SELECT id FROM qr_message WHERE wamid = $1`, [quotedId]);
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

  const senderJid = reaction.senderId || "";
  if (
    senderJid.includes("status@broadcast") ||
    senderJid.endsWith("@newsletter") ||
    senderJid.endsWith("@broadcast")
  ) {
    return;
  }

  const client = getClient(sessionId);
  const resolvedSender = await resolveContactWaId({ client, jid: senderJid });
  const senderWaId = resolvedSender.waId || toWaId(senderJid);
  if (!senderWaId) return;

  const eventRow = await one(
    `INSERT INTO qr_event (session_id, kind, payload, status)
     VALUES ($1, 'reaction', $2, 'pending') RETURNING *`,
    [sessionId, reaction]
  );

  const session = await store.getSessionById(sessionId);
  const phoneNumber = store.visibleNumber(session);
  const metaPayload = inboundReaction(reaction);
  if (metaPayload.messages && metaPayload.messages[0]) {
    metaPayload.messages[0].from = senderWaId;
  }

  const targetWamid = reaction.msgId?._serialized || String(reaction.msgId || "");
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

  const fromJid = message.from || "";
  const toJid = message.to || "";
  if (
    fromJid.includes("status@broadcast") ||
    toJid.includes("status@broadcast") ||
    fromJid.endsWith("@newsletter") ||
    toJid.endsWith("@newsletter") ||
    fromJid.endsWith("@broadcast") ||
    toJid.endsWith("@broadcast")
  ) {
    return;
  }

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
