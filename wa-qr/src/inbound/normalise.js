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
};

/** A wa_id as Meta writes it: digits only, no @c.us suffix. */
export function toWaId(serialised) {
  return String(serialised || "").split("@")[0].replace(/\D/g, "");
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
 */
export function inboundMessage(message, { contactName = "", media = null, quotedId = "" } = {}) {
  const kind = kindOf(message);
  const from = toWaId(message.from);

  const out = {
    from,
    id: message.id?._serialized || String(message.id || ""),
    // Meta sends seconds since the epoch as a string; the library gives seconds.
    timestamp: String(message.timestamp || Math.floor(Date.now() / 1000)),
    type: kind,
  };

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
        id: reaction.id?._serialized || String(reaction.id || ""),
        timestamp: String(reaction.timestamp || Math.floor(Date.now() / 1000)),
        type: "reaction",
        reaction: {
          message_id: reaction.msgId?._serialized || String(reaction.msgId || ""),
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
        id: message.id?._serialized || String(message.id || ""),
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
