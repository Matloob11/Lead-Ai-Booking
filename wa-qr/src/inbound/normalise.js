/**
 * Rewrites whatsapp-web.js events into the JSON the alots.io gateway sends.
 *
 * This is the whole reason the two halves can be joined later without a second
 * parser. `backend/apps/gateway/tasks.py` already knows how to read a Meta
 * webhook body — which contact wrote, what kind of message it was, which
 * message it quoted — so rather than teach it a second dialect, everything
 * coming off the phone is translated into the dialect it speaks.
 *
 * Anything that cannot be expressed in that shape is a sign the two channels
 * genuinely differ, and belongs in `payload` rather than invented into a field.
 */

/** whatsapp-web.js message types → the Cloud API's names for the same things. */
const KIND = {
  chat: "text",
  image: "image",
  video: "video",
  ptt: "audio", // a held-to-record voice note
  audio: "audio",
  document: "document",
  sticker: "sticker",
  location: "location",
  vcard: "contacts",
  multi_vcard: "contacts",

  // Everything below used to fall through to "unknown", and 878 messages —
  // one in sixteen — were sitting in the panel as the literal text
  // "[unknown]". Most of them are ordinary things WhatsApp does: a message
  // somebody deleted, a poll, a missed call, the pairing notices the app sends
  // itself. None of that is a mystery worth showing an agent as one.
  //
  // The names on the right are Meta's own where Meta has one, so the payload
  // this builds stays in the dialect `apps/gateway/tasks.py` already reads.
  // `deleted` is the exception: Meta's webhook has no word for a message that
  // was withdrawn, and "unsupported" would be a worse lie than a new word.
  revoked: "deleted",
  ciphertext: "pending", // arrived before the key did; usually resolves itself
  poll_creation: "poll",
  poll_update: "poll",
  call_log: "call",
  order: "order",
  product: "product",
  list: "interactive",
  list_response: "interactive",
  buttons_response: "interactive",
  template_button_reply: "interactive",
  groups_v4_invite: "invite",

  // Found by asking the phone what the leftover "unknown" rows were, which is
  // the whole reason `_type` is recorded below. None of these is exotic —
  // they were simply never written down.
  //
  // `album` is the wrapper WhatsApp sends when somebody picks several photos at
  // once; the photos themselves arrive as their own image messages beside it,
  // so this row is a marker rather than a picture. Kept rather than dropped,
  // because "they sent four photos together" is worth seeing.
  album: "album",
  interactive: "interactive",
  pinned_message: "pinned",
  automated_greeting_message: "text",
  biz_content_placeholder: "unsupported",

  // Housekeeping between two copies of WhatsApp. Never worth a bubble.
  e2e_notification: "system",
  notification_template: "system",
  gp2: "system",
  protocol: "system",
  broadcast_notification: "system",
};

/** A wa_id as Meta writes it: digits only, no @c.us suffix. */
export function toWaId(serialised) {
  return String(serialised || "").split("@")[0].replace(/\D/g, "");
}

/**
 * A message's id as a string, whatever shape the library hands it over in.
 *
 * `id._serialized` is the documented field and is missing on this build, where
 * the same value arrives under `$1` — a minified name that will change again.
 * Falling back to String(id) turned every message into the literal text
 * "[object Object]", which the first row claimed and the unique index then
 * refused to every message after it: the conversation's counters moved while
 * not a single message was stored.
 *
 * Rebuilding it from the parts is the last resort and the most durable one —
 * fromMe, remote and id are the three fields WhatsApp's own format is made of.
 */
export function messageId(id) {
  if (!id) return "";
  if (typeof id === "string") return id;
  if (typeof id._serialized === "string" && id._serialized) return id._serialized;
  if (typeof id.$1 === "string" && id.$1) return id.$1;
  if (id.id && id.remote) return `${id.fromMe ? "true" : "false"}_${id.remote}_${id.id}`;
  return "";
}

/**
 * Puts the id back where whatsapp-web.js expects to find it.
 *
 * Every method that goes back to the page for more — downloadMedia,
 * getQuotedMessage, react, forward, delete — passes `this.id._serialized`
 * through to `Msg.get(...)`. On this build that field does not exist, so each
 * of them looks up `undefined`, gets nothing, and dies inside WhatsApp's own
 * minified code as a one-letter error with no clue in it.
 *
 * It has cost three separate features so far: every message stored under the
 * id "[object Object]", every attachment failing to download, and 763 replies
 * losing the link to the message they answered. Setting it once, on the way in,
 * is cheaper than remembering it at each of the call sites.
 */
export function ensureSerialized(message) {
  if (message?.id && typeof message.id._serialized !== "string") {
    message.id._serialized = messageId(message.id);
  }
  return message;
}

/**
 * Resolves a WhatsApp JID (whether @c.us, @g.us, or @lid) to a real phone number wa_id.
 * If the JID is @lid, queries whatsapp-web.js Contact/Client to retrieve the real phone number.
 */
export async function resolveContactWaId({ client = null, jid = "", message = null } = {}) {
  if (!jid) return { waId: "", lid: "", isLid: false };

  // 1. Group chats -> wa_id is group ID (digits from @g.us)
  if (jid.endsWith("@g.us")) {
    return { waId: toWaId(jid), lid: "", isLid: false };
  }

  // 2. Ignore broadcasts, status, newsletters
  if (
    jid.includes("status@broadcast") ||
    jid.endsWith("@newsletter") ||
    jid.endsWith("@broadcast")
  ) {
    return { waId: "", lid: "", isLid: false };
  }

  const isLid = jid.endsWith("@lid");
  const lid = isLid ? jid : "";

  // Standard @c.us format
  if (!isLid && jid.endsWith("@c.us")) {
    return { waId: toWaId(jid), lid: "", isLid: false };
  }

  // Ask WhatsApp itself. This is the only thing that actually knows which
  // number is behind a LinkedID, and it is tried before anything else.
  //
  // getContact() is deliberately not trusted here. On an outbound message it
  // returns *our own* contact, not the customer's — the log showed it handing
  // back the linked phone's own number while resolving the customer's chat —
  // and its `.number` field is itself sometimes another LinkedID. Believing
  // either produced a contact that looked like a phone number, could not be
  // dialled, and appeared beside the same person's real chat as a duplicate.
  //
  // Each step says what it found. Two rounds of reasoning about why a LinkedID
  // kept being stored produced two wrong answers, because every path out of
  // here was silent — a null client, an empty result and a thrown error all
  // looked identical from the outside.
  if (!client) {
    console.warn(`[wa-qr] no live client for ${jid} — cannot ask WhatsApp for the number`);
  } else if (typeof client.getContactLidAndPhone !== "function") {
    console.warn("[wa-qr] this whatsapp-web.js has no getContactLidAndPhone");
  } else {
    try {
      const res = await client.getContactLidAndPhone([jid]);
      const pn = res?.[0]?.pn || "";
      const resolvedWaId = toWaId(pn);
      if (resolvedWaId) {
        return { waId: resolvedWaId, lid: res[0].lid || lid, isLid: true };
      }
      console.warn(`[wa-qr] WhatsApp returned no number for ${jid}: ${JSON.stringify(res)}`);
    } catch (err) {
      console.warn(`[wa-qr] getContactLidAndPhone(${jid}) threw: ${err.message}`);
    }
  }

  // Last resort: the message's own contact, but only when it is demonstrably
  // the party being resolved. The check is the whole point — without it this
  // returns the sender, which on anything we sent is ourselves.
  if (message && typeof message.getContact === "function") {
    try {
      const contact = await message.getContact();
      const sameParty = messageId(contact?.id) === jid;
      if (sameParty && contact.id.server === "c.us" && contact.id.user) {
        return { waId: toWaId(contact.id.user), lid, isLid };
      }
    } catch (err) {
      console.warn(`[wa-qr] getContact() for ${jid} threw: ${err.message}`);
    }
  }

  // Nothing knew the number. For a plain @c.us that is fine — the jid is the
  // number. For a LinkedID it is not: the digits are an internal id, and
  // storing them as a phone number makes a chat that looks real, cannot be
  // replied to, and sits beside the same person's real chat as a duplicate.
  //
  // It is still stored rather than dropped, because losing the customer's
  // message is worse than holding it under a name we cannot dial — but it says
  // so out loud instead of failing quietly.
  const extracted = toWaId(jid);
  if (isLid) {
    console.warn(
      `[wa-qr] could not resolve ${jid} to a phone number — the chat will be ` +
        `stored under the LinkedID and cannot be replied to`
    );
  }
  return { waId: extracted, lid: isLid ? jid : "", isLid, resolutionFailed: isLid };
}

export function kindOf(message) {
  return KIND[message?.type] || "unknown";
}

/**
 * One inbound message, in Meta's `messages` shape.
 *
 * `media` and `quotedId` are passed in rather than read off the message: both
 * need an await to obtain — `downloadMedia()` and `getQuotedMessage()` — and
 * this function stays synchronous and pure so it can be tested with no phone
 * attached. It also leaves the caller deciding whether a 40 MB video is worth
 * pulling.
 *
 * @param {object}  message
 * @param {string}  [options.contactName]  the sender's WhatsApp profile name
 * @param {object}  [options.media]        an already-downloaded attachment
 * @param {string}  [options.quotedId]     `_serialized` id of the quoted
 *                                         message, from getQuotedMessage()
 * @param {string}  [options.waId]         the sender's real phone number, from
 *                                         resolveContactWaId(). Required for a
 *                                         @lid chat, where message.from is a
 *                                         LinkedID and not a number at all.
 */
export function inboundMessage(
  message,
  { contactName = "", media = null, quotedId = "", waId = "" } = {}
) {
  const kind = kindOf(message);
  // Both fields, not just the contact: the receiving side keys on
  // messages[0].from, so leaving a LinkedID there would recreate the very row
  // the resolution exists to avoid.
  const from = waId || toWaId(message.from);

  const out = {
    from,
    id: messageId(message.id),
    // Meta sends seconds since the epoch as a string; the library gives seconds.
    timestamp: String(message.timestamp || Math.floor(Date.now() / 1000)),
    type: kind,
  };

  // What the library called it, kept alongside what we called it.
  //
  // Underscored so it reads as ours rather than as part of Meta's shape. It
  // exists because 878 messages ended up stored as "unknown" and there was no
  // way left to ask what any of them had been — the raw type was thrown away at
  // exactly the point it stopped being understood. The next type WhatsApp
  // invents will be answerable with one query instead of a guess.
  if (kind === "unknown" && message.type) out._type = String(message.type);

  if (kind === "text") {
    out.text = { body: message.body || "" };
  } else if (kind === "location") {
    // Numbers, not strings. The Cloud gateway rejects strings outright, and a
    // payload that only works on one of the two channels is the thing this
    // whole file exists to avoid.
    out.location = {
      latitude: Number(message.location?.latitude),
      longitude: Number(message.location?.longitude),
      name: message.location?.name || "",
      address: message.location?.address || "",
    };
  } else if (media) {
    out[kind] = {
      id: media.id || "",
      mime_type: media.mimetype || "",
      sha256: media.sha256 || "",
      filename: media.filename || "",
      caption: message.body || "",
      // Where our own copy lives. The Cloud side calls the gateway's hosted
      // copy `filelink` and prefers it over Meta's expiring link, so the same
      // name is used for the same job.
      filelink: media.filelink || "",
    };
  }

  // A quoted message is named by id, exactly as Meta names it. The library
  // only offers hasQuotedMsg plus an async getter, so the id arrives from the
  // caller; without it a reply would still be stored, just not joined to what
  // it answers.
  if (quotedId) {
    out.context = { id: quotedId };
  }

  return {
    contacts: [{ wa_id: from, profile: { name: contactName || "" } }],
    messages: [out],
  };
}

/** A reaction. It names the message it decorates; an empty emoji takes it back. */
export function inboundReaction(reaction) {
  return {
    contacts: [],
    messages: [
      {
        from: toWaId(reaction.senderId),
        id: messageId(reaction.id),
        timestamp: String(reaction.timestamp || Math.floor(Date.now() / 1000)),
        type: "reaction",
        reaction: {
          message_id: messageId(reaction.msgId),
          emoji: reaction.reaction || "",
        },
      },
    ],
  };
}

/**
 * A delivery receipt.
 *
 * whatsapp-web.js counts acks 0..4; Meta names four states and has no word for
 * "the server has it but the phone has not". That one maps to `sent`, which is
 * what it means.
 */
const ACK = { 0: "sent", 1: "sent", 2: "delivered", 3: "read", 4: "read", "-1": "failed" };

export function statusUpdate(message, ack) {
  const status = ACK[String(ack)] || "sent";
  return {
    contacts: [],
    statuses: [
      {
        id: messageId(message.id),
        recipient_id: toWaId(message.to),
        status,
        timestamp: String(Math.floor(Date.now() / 1000)),
      },
    ],
  };
}

/**
 * Wraps a value block in the entry/changes envelope Meta puts around
 * everything, so a receiver cannot tell which channel it came from.
 *
 * `phoneNumberId` is the linked phone's own number here — there is no separate
 * Meta id for a QR session, and the field is what the receiver keys on.
 */
export function envelope(value, phoneNumberId) {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: String(phoneNumberId || ""),
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: {
                display_phone_number: String(phoneNumberId || ""),
                phone_number_id: String(phoneNumberId || ""),
              },
              ...value,
            },
          },
        ],
      },
    ],
  };
}
