/**
 * Outbound Message Sending Engine
 */

import path from "node:path";
import pkg from "whatsapp-web.js";
const { MessageMedia, Location } = pkg;

import { mediaRoot } from "../config.js";
import { getClient } from "../sessions/manager.js";
import * as store from "../sessions/store.js";
import { toWaId, resolveContactWaId } from "../inbound/normalise.js";
import { q, one } from "../db.js";

export async function sendOutboundMessage({
  session_id,
  to,
  kind = "text",
  body = "",
  media_path = "",
  reply_to_id = null,
  latitude = null,
  longitude = null,
  name = "",
  address = "",
}) {
  const sessionId = Number(session_id);
  if (!sessionId || !to) {
    throw new Error("session_id and to recipient are required");
  }

  const session = await store.getSessionById(sessionId);
  if (!session || session.status === "banned") {
    throw new Error("Session is invalid or banned");
  }

  const client = getClient(sessionId);
  const isGroup = String(to).endsWith("@g.us");

  let recipientWaId = toWaId(to);

  // If 'to' is LID JID or a 15-digit number (LID digits), resolve phone number via client
  if (String(to).endsWith("@lid") || (recipientWaId.length > 14 && !isGroup)) {
    if (client) {
      const lidJid = String(to).endsWith("@lid") ? to : `${recipientWaId}@lid`;
      const resolved = await resolveContactWaId({ client, jid: lidJid });
      if (resolved?.waId && resolved.waId.length <= 14) {
        recipientWaId = resolved.waId;
      }
    }
  }

  // If recipientWaId is still invalid LID digits (>14 digits for individual chat)
  if (recipientWaId.length > 14 && !isGroup) {
    const errorMsg = `Cannot send to LID: could not resolve phone number for ${to}`;
    throw new Error(errorMsg);
  }

  // 1. Get or create Contact
  const contactRow = await one(
    `INSERT INTO qr_contact (wa_id, profile_name, display_name)
     VALUES ($1, $1, $1)
     ON CONFLICT (wa_id) DO UPDATE SET wa_id = EXCLUDED.wa_id
     RETURNING id`,
    [recipientWaId]
  );
  const contactId = Number(contactRow.id);

  // 2. Get or create Conversation
  const convRow = await one(
    `INSERT INTO qr_conversation (session_id, contact_id, is_group, subject, last_message_at, last_message_preview, last_message_kind)
     VALUES ($1, $2, $3, $4, now(), $5, $6)
     ON CONFLICT (session_id, contact_id) DO UPDATE SET
       last_message_at = now(),
       last_message_preview = EXCLUDED.last_message_preview,
       last_message_kind = EXCLUDED.last_message_kind
     RETURNING id`,
    [sessionId, contactId, isGroup, isGroup ? recipientWaId : "", body.slice(0, 200), kind]
  );
  const conversationId = Number(convRow.id);

  // 3. Create qr_message row FIRST with status='queued' and wamid=NULL
  const msgRow = await one(
    `INSERT INTO qr_message (conversation_id, direction, kind, body, reply_to_id, status)
     VALUES ($1, 'out', $2, $3, $4, 'queued')
     RETURNING *`,
    [conversationId, kind, body, reply_to_id ? Number(reply_to_id) : null]
  );
  const messageId = Number(msgRow.id);

  // 4. Fetch Client instance
  if (!client) {
    const errorMsg = "WhatsApp client is not connected for this session";
    await q(`UPDATE qr_message SET status = 'failed', error_detail = $1 WHERE id = $2`, [
      errorMsg,
      messageId,
    ]);
    throw new Error(errorMsg);
  }

  const formattedTo = isGroup ? to : `${recipientWaId}@c.us`;
  const sendOptions = {};

  // Quote handling
  if (reply_to_id) {
    const parentMsg = await one(`SELECT wamid FROM qr_message WHERE id = $1`, [
      reply_to_id,
    ]);
    if (parentMsg?.wamid) {
      sendOptions.quotedMessageId = parentMsg.wamid;
    }
  }

  try {
    let sentMsg = null;

    if (kind === "location" && latitude !== null && longitude !== null) {
      const loc = new Location(Number(latitude), Number(longitude), { name, address });
      sentMsg = await client.sendMessage(formattedTo, loc, sendOptions);
    } else if (
      ["image", "video", "audio", "document", "sticker"].includes(kind) &&
      media_path
    ) {
      const absolutePath = path.isAbsolute(media_path)
        ? media_path
        : path.join(mediaRoot, media_path);
      const media = MessageMedia.fromFilePath(absolutePath);
      sentMsg = await client.sendMessage(formattedTo, media, {
        caption: body,
        sendMediaAsSticker: kind === "sticker",
        ...sendOptions,
      });
    } else {
      // Default text
      sentMsg = await client.sendMessage(formattedTo, body, sendOptions);
    }

    const wamid = sentMsg.id?._serialized || String(sentMsg.id || "");

    // 5. Update DB status='sent' + wamid on success
    const updatedRow = await one(
      `UPDATE qr_message
       SET status = 'sent', wamid = $1, payload = $2
       WHERE id = $3
       RETURNING *`,
      [wamid, sentMsg.rawData || sentMsg._data || {}, messageId]
    );

    await q(
      `UPDATE qr_conversation
       SET last_message_at = now(), last_message_preview = $1, last_message_kind = $2
       WHERE id = $3`,
      [body.slice(0, 200), kind, conversationId]
    );

    return updatedRow;
  } catch (err) {
    const errorMsg = err.message || "Failed to send message via WhatsApp";
    await q(`UPDATE qr_message SET status = 'failed', error_detail = $1 WHERE id = $2`, [
      errorMsg,
      messageId,
    ]);
    throw new Error(errorMsg);
  }
}
