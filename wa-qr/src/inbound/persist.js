/**
 * Event Persistence and DB Synchronisation
 */

import { onEvent, getClient } from "../sessions/manager.js";
import * as store from "../sessions/store.js";
import {
  ensureSerialized,
  messageId,
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

/** A message that has just arrived on a live socket. */
async function processMessageEvent(sessionId, message) {
  return storeMessage(sessionId, message);
}

/**
 * When a message was actually sent, as opposed to when we read it.
 *
 * An imported message is months old and has to be stored under its own time or
 * the whole history lands in this afternoon, every chat claims to have been
 * active seconds ago, and the order a conversation is read in is lost.
 *
 * A timestamp before WhatsApp existed is not a timestamp, it is a missing
 * field, and now() is the honest answer to when we learned of it.
 */
const EARLIEST = Date.UTC(2009, 0, 1);

function sentAt(message) {
  const ms = Number(message?.timestamp || 0) * 1000;
  return new Date(ms > EARLIEST && ms < Date.now() + 86_400_000 ? ms : Date.now());
}

/**
 * Writes one message down, whether it just arrived or is being imported.
 *
 * Both paths share this deliberately. They differ in ways that are easy to
 * state — an imported message is not unread, does not move the chat to the top
 * unless it really is the newest, is not announced to anyone, and carries its
 * own date — and every other detail is the same. Two separate writers would
 * drift, and the one nobody watches is the one that quietly stores something
 * different from the other.
 *
 * @param {boolean} [options.historical]  read back from the phone, not live
 * @param {boolean} [options.repair]      allowed to overwrite a row that is
 *                                        still `kind = 'unknown'`, and only
 *                                        that. Everything else is refused by
 *                                        the unique index as usual.
 * @param {boolean} [options.withMedia]   download attachments (import only —
 *                                        six months of video is not worth
 *                                        pulling, thirty days of it is)
 * @param {object}  [options.contact]     `{waId, name}` already worked out by
 *                                        the caller. Both lookups it saves are
 *                                        round trips into the browser, and an
 *                                        import asks the same question of the
 *                                        same chat once per message otherwise —
 *                                        thousands of evaluations for an answer
 *                                        that cannot change within one chat.
 * @returns {Promise<{stored: boolean}>}  whether a new row was written
 */
export async function storeMessage(sessionId, message, options = {}) {
  const { historical = false, withMedia = true, contact = null, repair = false } = options;
  const live = !historical;

  if (!message) return { stored: false };

  // Before anything asks the library for more about this message. Everything
  // that does — the quoted message, the attachment, a reaction — looks itself
  // up by `id._serialized`, which this build does not set.
  ensureSerialized(message);

  const wamid = messageId(message.id);
  if (!wamid) return { stored: false };

  const occurredAt = sentAt(message);
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
    if (live) {
      console.info(`[wa-qr] Ignoring status/newsletter/broadcast message event (${fromJid || remoteJid})`);
    }
    return { stored: false };
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
    return { stored: false };
  }

  // WhatsApp talking to itself.
  //
  // Pairing notices, protocol messages, the housekeeping two copies of the app
  // exchange. These were being stored, and storing them was worse than drawing
  // them: each one creates a contact and a conversation, moves that chat to the
  // top of the list on its own, and leaves "System" sitting where the last
  // thing somebody said belongs. One chat in the list held nothing else at all.
  //
  // Dropped here, with status and newsletter traffic, rather than hidden in the
  // panel — a message nobody sent should not be a row.
  if (kindOf(message) === "system") return { stored: false };

  const client = getClient(sessionId);

  // Fetch contact info & resolve wa_id
  let contactName = contact?.name || "";
  if (!contact) {
    try {
      const who = await message.getContact();
      contactName = who.name || who.pushname || "";
    } catch {}
  }

  const direction = message.fromMe ? "out" : "in";
  const kind = kindOf(message);
  const body = message.body || "";
  const isGroup = Boolean(message.from?.endsWith("@g.us"));
  const rawTargetJid = isGroup
    ? message.from
    : direction === "in"
      ? message.from
      : message.to;

  const contactWaId =
    contact?.waId || (await resolveContactWaId({ client, jid: rawTargetJid, message })).waId;

  if (!contactWaId) {
    console.warn(`[wa-qr] Could not resolve valid contact wa_id for JID ${rawTargetJid}, skipping message persistence.`);
    return { stored: false };
  }

  let authorWaId = "";
  if (isGroup && (message.author || message.from)) {
    const resolvedAuthor = await resolveContactWaId({ client, jid: message.author || message.from, message });
    authorWaId = resolvedAuthor.waId;
  }

  // The event log is a record of what reached us, and an import did not reach
  // us — it was fetched. Writing one row per imported message would put six
  // months of history through a table whose purpose is re-parsing today's
  // webhook when today's parser turns out to be wrong.
  const eventRow = live
    ? await one(
        `INSERT INTO qr_event (session_id, kind, payload, status)
         VALUES ($1, 'message', $2, 'pending') RETURNING *`,
        [sessionId, message.rawData || message._data || {}]
      )
    : null;

  const session = await store.getSessionById(sessionId);
  const phoneNumber = store.visibleNumber(session);

  // What we already hold for this message, if anything.
  //
  // Asked before the attachment is fetched, because fetching it first is what
  // was happening and it was expensive in the worst way. A catch-up import
  // re-reads whatever overlaps what it already has; the insert below refuses
  // those by wamid — but by then the file had been downloaded, and the qr_media
  // row it created pointed at nothing. 767 files came down that way in two
  // hours, every one of them a copy of a file already on disk.
  //
  // The cost is not the disk. It is asking WhatsApp for the same media over and
  // over from a personal number, which is the kind of load these accounts get
  // banned for — the thing `/api/risk` exists to watch for elsewhere.
  const already = await one(`SELECT id, media_id FROM qr_message WHERE wamid = $1`, [wamid]);

  // Fetch only when it would land somewhere: a message we have never seen, or
  // one being repaired that never got its attachment.
  const wantMedia =
    message.hasMedia && withMedia && (!already || (repair && !already.media_id));
  const mediaRecord = wantMedia ? await processInboundMedia(message) : null;

  // Which message this one answers, if any.
  let quotedId = "";
  if (message.hasQuotedMsg) {
    try {
      const quoted = await message.getQuotedMessage();
      quotedId = messageId(quoted?.id);
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
  //
  // An imported message is only the chat's latest if it really is the latest.
  // Stamping now() the way the live path used to would march every chat to the
  // top of the list in whatever order the import happened to read them, and
  // overwrite this morning's preview with something from March.
  //
  // Nothing imported counts as unread either. The badge answers "what has come
  // in that nobody has looked at", and a message from three months ago is not
  // news however recently we learned of it.
  const unreadBump = live && direction === "in" ? 1 : 0;

  const conversationRow = await one(
    `INSERT INTO qr_conversation (session_id, contact_id, is_group, subject, last_message_at, last_message_preview, last_message_kind, unread_count)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
     ON CONFLICT (session_id, contact_id) DO UPDATE SET
       last_message_at = GREATEST(qr_conversation.last_message_at, EXCLUDED.last_message_at),
       last_message_preview = CASE
         WHEN qr_conversation.last_message_at IS NULL
           OR EXCLUDED.last_message_at >= qr_conversation.last_message_at
         THEN EXCLUDED.last_message_preview ELSE qr_conversation.last_message_preview END,
       last_message_kind = CASE
         WHEN qr_conversation.last_message_at IS NULL
           OR EXCLUDED.last_message_at >= qr_conversation.last_message_at
         THEN EXCLUDED.last_message_kind ELSE qr_conversation.last_message_kind END,
       unread_count = qr_conversation.unread_count + $9
     RETURNING id`,
    [
      sessionId,
      contactId,
      isGroup,
      isGroup ? contactName : "",
      occurredAt,
      body.slice(0, 200),
      kind,
      unreadBump,
      unreadBump,
    ]
  );
  const conversationId = Number(conversationRow.id);

  // 3. Message row with ON CONFLICT (wamid) DO NOTHING
  const initialStatus = direction === "in" ? "received" : message.ack ? statusUpdate(message, message.ack).statuses[0].status : "sent";

  // Something we sent ourselves comes back here through message_create, and
  // the composer has already written a row for it and left it queued because
  // sendMessage answers with nothing on this WhatsApp build. Settle that row
  // rather than adding a second one beside it — otherwise every message an
  // agent sends appears twice, once stuck queued and once complete.
  if (live && direction === "out") {
    const pending = await one(
      `UPDATE qr_message
          SET wamid = $1, status = $2, payload = $3
        WHERE id = (
          SELECT id FROM qr_message
           WHERE conversation_id = $4
             AND direction = 'out'
             AND wamid IS NULL
             AND body = $5
             AND created_at > now() - interval '2 minutes'
           ORDER BY created_at DESC
           LIMIT 1)
        RETURNING id`,
      [wamid, initialStatus, metaPayload, conversationId, body]
    );
    if (pending) {
      await q(`UPDATE qr_event SET status = 'processed' WHERE id = $1`, [eventRow.id]);
      await emitWebhook(eventRow.id, metaPayload, phoneNumber);
      return { stored: true };
    }
  }

  // RETURNING tells the two apart: a row written, or one the unique index
  // already held. An import re-reads whatever overlaps what it has, so without
  // this the count it reports would be of messages seen, not messages kept.
  //
  // `repair` is the one case that may overwrite. 878 rows were stored before
  // the raw WhatsApp type was kept anywhere, so their real type is gone and
  // only WhatsApp can say what they were — but DO NOTHING means re-reading them
  // changes nothing at all, which is why they have stayed broken.
  //
  // The WHERE on the update is the whole safety of it. Only a row that is
  // still 'unknown' is touched; anything already identified is left exactly as
  // it is, so a repair pass that runs twice, or over a chat that needed
  // nothing, cannot damage a single correct row.
  // Deliberately not `AND EXCLUDED.kind <> 'unknown'`. The first run of this
  // named 52 of one phone's 93 and left 41 — and because the update was
  // refused for those, their payload was never written either, so the raw
  // WhatsApp type normalise.js now records went missing with them. The answer
  // to "what were the other 41?" was thrown away a second time by the guard
  // meant to protect them.
  //
  // The row is already 'unknown', so re-reading it can only leave it that way
  // or improve it. Writing the payload regardless is what turns the leftovers
  // from a dead end into a list of type names the KIND map can be extended
  // with.
  const onConflict = repair
    ? `ON CONFLICT (wamid) DO UPDATE
         SET kind = EXCLUDED.kind,
             payload = EXCLUDED.payload,
             -- COALESCE, so a repair can add the attachment a row never got
             -- but can never replace one it already has. Without this the
             -- media the repair had just downloaded was left unreferenced,
             -- which is how the orphan rows started.
             media_id = COALESCE(qr_message.media_id, EXCLUDED.media_id)
       WHERE qr_message.kind = 'unknown'`
    : `ON CONFLICT (wamid) DO NOTHING`;

  const inserted = await one(
    `INSERT INTO qr_message (conversation_id, direction, kind, wamid, body, media_id, reply_to_id, author_wa_id, status, payload, created_at)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
     ${onConflict}
     RETURNING id`,
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
      occurredAt,
    ]
  );

  // 4. Mark event processed and emit webhook
  if (eventRow) {
    await q(`UPDATE qr_event SET status = 'processed' WHERE id = $1`, [eventRow.id]);
    await emitWebhook(eventRow.id, metaPayload, phoneNumber);
  }

  return { stored: Boolean(inserted) };
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

  const targetWamid = messageId(reaction.msgId);
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
    [sessionId, { ack, wamid: messageId(message.id) }]
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
