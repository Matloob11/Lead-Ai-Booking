/**
 * Outbound WhatsApp Actions Engine
 *
 * Implements actions supported by QR channel (reactions, blue ticks / sendSeen,
 * typing indicators, forwarding, and delete for everyone).
 */

import { getClient } from "../sessions/manager.js";
import * as store from "../sessions/store.js";
import { messageId, toWaId } from "../inbound/normalise.js";
import { q, one } from "../db.js";

/** React to a message with an emoji, or remove reaction if emoji is empty. */
export async function reactToMessage({ session_id, wamid, emoji = "" }) {
  const sessionId = Number(session_id);
  if (!sessionId || !wamid) {
    throw new Error("session_id and wamid are required");
  }

  const client = getClient(sessionId);
  if (!client) {
    throw new Error(`WhatsApp client not connected for session #${sessionId}`);
  }

  const msgRow = await one(`SELECT id, conversation_id, reactions FROM qr_message WHERE wamid = $1`, [
    wamid,
  ]);
  if (!msgRow) {
    throw new Error(`Message with wamid '${wamid}' not found`);
  }

  const msg = await client.getMessageById(wamid);
  if (!msg) {
    throw new Error(`WhatsApp message '${wamid}' could not be fetched from client`);
  }

  // CRITICAL FIX: Ensure _serialized is present so whatsapp-web.js methods do not crash
  if (msg.id) {
    msg.id._serialized = messageId(msg.id);
  }

  // React via whatsapp-web.js
  await msg.react(emoji || "");

  // Update DB reactions column
  const session = await store.getSessionById(sessionId);
  const senderWaId = store.visibleNumber(session);

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

  return { success: true, wamid, emoji: emoji || "" };
}

/** Mark conversation as read / blue ticks (sendSeen). */
export async function markChatSeen({ session_id, conversation_id }) {
  const sessionId = Number(session_id);
  const conversationId = Number(conversation_id);
  if (!sessionId || !conversationId) {
    throw new Error("session_id and conversation_id are required");
  }

  const client = getClient(sessionId);
  if (!client) {
    throw new Error(`WhatsApp client not connected for session #${sessionId}`);
  }

  const conv = await one(
    `SELECT conv.id, conv.is_group, c.wa_id
     FROM qr_conversation conv
     JOIN qr_contact c ON conv.contact_id = c.id
     WHERE conv.id = $1 AND conv.session_id = $2`,
    [conversationId, sessionId]
  );
  if (!conv) {
    throw new Error(`Conversation #${conversationId} not found for session #${sessionId}`);
  }

  const chatJid = conv.is_group ? `${conv.wa_id}@g.us` : `${conv.wa_id}@c.us`;
  const chat = await client.getChatById(chatJid);
  if (chat && typeof chat.sendSeen === "function") {
    await chat.sendSeen();
  }

  await q(`UPDATE qr_conversation SET unread_count = 0 WHERE id = $1`, [conversationId]);
  return { success: true, conversation_id: conversationId };
}

/** Set or clear typing indicator ("typing..."). */
export async function setTyping({ session_id, conversation_id, typing = true }) {
  const sessionId = Number(session_id);
  const conversationId = Number(conversation_id);
  if (!sessionId || !conversationId) {
    throw new Error("session_id and conversation_id are required");
  }

  const client = getClient(sessionId);
  if (!client) {
    throw new Error(`WhatsApp client not connected for session #${sessionId}`);
  }

  const conv = await one(
    `SELECT conv.id, conv.is_group, c.wa_id
     FROM qr_conversation conv
     JOIN qr_contact c ON conv.contact_id = c.id
     WHERE conv.id = $1 AND conv.session_id = $2`,
    [conversationId, sessionId]
  );
  if (!conv) {
    throw new Error(`Conversation #${conversationId} not found for session #${sessionId}`);
  }

  const chatJid = conv.is_group ? `${conv.wa_id}@g.us` : `${conv.wa_id}@c.us`;
  const chat = await client.getChatById(chatJid);

  if (chat) {
    if (typing) {
      if (typeof chat.sendStateTyping === "function") await chat.sendStateTyping();
    } else {
      if (typeof chat.clearState === "function") await chat.clearState();
    }
  }

  return { success: true, conversation_id: conversationId, typing: Boolean(typing) };
}

/** Forward an existing message to another contact or group. */
export async function forwardMessage({ session_id, wamid, to_wa_id }) {
  const sessionId = Number(session_id);
  const recipientWaId = toWaId(to_wa_id);
  if (!sessionId || !wamid || !recipientWaId) {
    throw new Error("session_id, wamid, and to_wa_id are required");
  }

  const client = getClient(sessionId);
  if (!client) {
    throw new Error(`WhatsApp client not connected for session #${sessionId}`);
  }

  const msg = await client.getMessageById(wamid);
  if (!msg) {
    throw new Error(`WhatsApp message '${wamid}' could not be fetched from client`);
  }

  // CRITICAL FIX: Ensure _serialized is present
  if (msg.id) {
    msg.id._serialized = messageId(msg.id);
  }

  const isGroup = String(to_wa_id).endsWith("@g.us");
  const formattedTo = isGroup ? to_wa_id : `${recipientWaId}@c.us`;

  await msg.forward(formattedTo);
  return { success: true, wamid, forwarded_to: recipientWaId };
}

/** Delete a message for everyone on WhatsApp. */
export async function deleteForEveryone({ session_id, wamid }) {
  const sessionId = Number(session_id);
  if (!sessionId || !wamid) {
    throw new Error("session_id and wamid are required");
  }

  const client = getClient(sessionId);
  if (!client) {
    throw new Error(`WhatsApp client not connected for session #${sessionId}`);
  }

  const msg = await client.getMessageById(wamid);
  if (!msg) {
    throw new Error(`WhatsApp message '${wamid}' could not be fetched from client`);
  }

  // CRITICAL FIX: Ensure _serialized is present
  if (msg.id) {
    msg.id._serialized = messageId(msg.id);
  }

  // Delete for everyone (everyone = true)
  await msg.delete(true);

  // Mark deleted_at in DB
  await q(
    `UPDATE qr_message
     SET deleted_at = now()
     WHERE wamid = $1`,
    [wamid]
  );

  return { success: true, wamid };
}
