/**
 * Outbound WhatsApp Actions Engine
 *
 * Implements actions supported by QR channel (reactions, blue ticks / sendSeen,
 * typing indicators, forwarding, and delete for everyone).
 */

import pkg from "whatsapp-web.js";
const { PrivateChat, GroupChat } = pkg;

import { getClient } from "../sessions/manager.js";
import * as store from "../sessions/store.js";
import { messageId, toWaId } from "../inbound/normalise.js";
import { q, one } from "../db.js";

/**
 * A Chat to act on, whether or not WhatsApp will describe one.
 *
 * getChatById builds a full model, and on this account that fails for every
 * chat addressed by LinkedID — which is most of them. The history import hit
 * exactly this and 161 chats came back with a one-letter minified error.
 *
 * sendSeen needs two things off a Chat: the client, and `id._serialized`. Those
 * are what it gets when the real model is refused.
 */
async function chatFor(client, jid) {
  const real = await client.getChatById(jid).catch(() => null);
  if (real) {
    if (real.id && typeof real.id._serialized !== "string") real.id._serialized = jid;
    return real;
  }

  const [user, server] = jid.split("@");
  const Klass = server === "g.us" ? GroupChat : PrivateChat;
  return new Klass(client, {
    id: { _serialized: jid, user, server },
    isGroup: server === "g.us",
  });
}

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

  // Told to the phone, and separately recorded here.
  //
  // The badge is ours and clears whatever WhatsApp does — a handset that is
  // offline, or a chat it will not describe, must not leave an agent looking at
  // a number that will not go away. So a failure here is reported and the
  // counter is zeroed regardless.
  let seenOnPhone = false;
  try {
    const chat = await chatFor(client, chatJid);
    if (chat && typeof chat.sendSeen === "function") {
      await chat.sendSeen();
      seenOnPhone = true;
    }
  } catch (error) {
    console.warn(`[wa-qr] could not mark ${chatJid} seen on the phone: ${error.message}`);
  }

  await q(`UPDATE qr_conversation SET unread_count = 0 WHERE id = $1`, [conversationId]);
  return { success: true, conversation_id: conversationId, seen_on_phone: seenOnPhone };
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
