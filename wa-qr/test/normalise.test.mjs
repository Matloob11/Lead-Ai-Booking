/**
 * Exercises normalise.js against the shapes whatsapp-web.js really emits.
 *
 * Pure functions with no imports, so this runs on plain node with nothing
 * installed — which is the point: three people are about to build on this file
 * and none of them should be the one to find out it is wrong.
 */

import assert from "node:assert/strict";
import {
  toWaId,
  kindOf,
  inboundMessage,
  inboundReaction,
  statusUpdate,
  envelope,
} from "../src/inbound/normalise.js";

let passed = 0;
const check = (name, fn) => {
  try {
    fn();
    passed++;
    console.log(`  ok    ${name}`);
  } catch (error) {
    console.log(`  FAIL  ${name}\n        ${error.message}`);
    process.exitCode = 1;
  }
};

check("wa_id drops the @c.us suffix and any punctuation", () => {
  assert.equal(toWaId("971501234567@c.us"), "971501234567");
  assert.equal(toWaId("+971 50 123 4567@c.us"), "971501234567");
  assert.equal(toWaId(undefined), "");
});

check("group ids reduce to digits too", () => {
  assert.equal(toWaId("971501234567-1600000000@g.us"), "9715012345671600000000");
});

check("library types map to the Cloud API's names", () => {
  assert.equal(kindOf({ type: "chat" }), "text");
  assert.equal(kindOf({ type: "ptt" }), "audio"); // a held-to-record voice note
  assert.equal(kindOf({ type: "vcard" }), "contacts");
  assert.equal(kindOf({ type: "something_new" }), "unknown");
});

check("a text message comes out in Meta's shape", () => {
  const out = inboundMessage(
    {
      from: "971501234567@c.us",
      id: { _serialized: "false_971501234567@c.us_ABC" },
      timestamp: 1754200000,
      type: "chat",
      body: "Do you have 3BR available",
    },
    { contactName: "Ahmed" }
  );

  assert.equal(out.messages[0].from, "971501234567");
  assert.equal(out.messages[0].type, "text");
  assert.equal(out.messages[0].text.body, "Do you have 3BR available");
  assert.equal(out.messages[0].timestamp, "1754200000"); // a string, as Meta sends
  assert.equal(out.contacts[0].profile.name, "Ahmed");
});

check("location coordinates are numbers, never strings", () => {
  const out = inboundMessage({
    from: "971501234567@c.us",
    id: { _serialized: "x" },
    type: "location",
    location: { latitude: "25.0657", longitude: "55.1713", name: "Damac Hills" },
  });

  const pin = out.messages[0].location;
  assert.equal(typeof pin.latitude, "number");
  assert.equal(typeof pin.longitude, "number");
  assert.equal(pin.latitude, 25.0657);
  assert.equal(pin.name, "Damac Hills");
});

check("media carries the caption and our own copy's link", () => {
  const out = inboundMessage(
    {
      from: "971501234567@c.us",
      id: { _serialized: "x" },
      type: "image",
      body: "the floorplan",
    },
    { media: { id: "9", mimetype: "image/jpeg", filelink: "/media/9.jpg", sha256: "abc" } }
  );

  const blob = out.messages[0].image;
  assert.equal(out.messages[0].type, "image");
  assert.equal(blob.caption, "the floorplan");
  assert.equal(blob.mime_type, "image/jpeg");
  assert.equal(blob.filelink, "/media/9.jpg");
});

check("media with nothing downloaded does not invent a blob", () => {
  const out = inboundMessage({
    from: "971501234567@c.us",
    id: { _serialized: "x" },
    type: "image",
    body: "too big to fetch",
  });
  assert.equal(out.messages[0].image, undefined);
});

check("a quote is named by id, the way Meta names it", () => {
  const out = inboundMessage({
    from: "971501234567@c.us",
    id: { _serialized: "x" },
    type: "chat",
    body: "yes please",
    hasQuotedMsg: true,
    hasQuotedMsg: true,
  }, { quotedId: "false_971501234567@c.us_QUOTED" });
  assert.equal(out.messages[0].context.id, "false_971501234567@c.us_QUOTED");
});

check("no quote means no context block at all", () => {
  const out = inboundMessage({
    from: "971501234567@c.us",
    id: { _serialized: "x" },
    type: "chat",
    body: "hi",
  });
  assert.equal("context" in out.messages[0], false);
});

check("a reaction names the message it decorates", () => {
  const out = inboundReaction({
    senderId: "971501234567@c.us",
    id: { _serialized: "r1" },
    msgId: { _serialized: "false_971501234567@c.us_TARGET" },
    reaction: "\u{1F44D}",
    timestamp: 1754200000,
  });

  assert.equal(out.messages[0].type, "reaction");
  assert.equal(out.messages[0].reaction.message_id, "false_971501234567@c.us_TARGET");
  assert.equal(out.messages[0].reaction.emoji, "\u{1F44D}");
});

check("an empty emoji is a reaction taken back", () => {
  const out = inboundReaction({
    senderId: "971501234567@c.us",
    id: { _serialized: "r2" },
    msgId: { _serialized: "t" },
    reaction: "",
  });
  assert.equal(out.messages[0].reaction.emoji, "");
});

check("acks map onto the four states Meta has words for", () => {
  const message = { id: { _serialized: "m1" }, to: "971501234567@c.us" };
  assert.equal(statusUpdate(message, 1).statuses[0].status, "sent");
  assert.equal(statusUpdate(message, 2).statuses[0].status, "delivered");
  assert.equal(statusUpdate(message, 3).statuses[0].status, "read");
  assert.equal(statusUpdate(message, -1).statuses[0].status, "failed");
  assert.equal(statusUpdate(message, 2).statuses[0].recipient_id, "971501234567");
});

check("the envelope is indistinguishable from a Cloud webhook", () => {
  const body = envelope(inboundMessage({
    from: "971501234567@c.us",
    id: { _serialized: "x" },
    type: "chat",
    body: "hi",
  }), "923001234567");

  const value = body.entry[0].changes[0].value;
  assert.equal(body.object, "whatsapp_business_account");
  assert.equal(body.entry[0].changes[0].field, "messages");
  assert.equal(value.messaging_product, "whatsapp");
  assert.equal(value.metadata.phone_number_id, "923001234567");
  assert.equal(value.messages[0].from, "971501234567");
  assert.ok(Array.isArray(value.contacts));
});

check("a resolved number replaces the LinkedID in both places", () => {
  // A @lid chat: message.from is a LinkedID, not a phone number at all.
  const out = inboundMessage(
    { from: "280908645044375@lid", id: { _serialized: "x" }, type: "chat", body: "hi" },
    { contactName: "Matloob Bhai", waId: "923166753715" }
  );

  assert.equal(out.messages[0].from, "923166753715");
  assert.equal(out.contacts[0].wa_id, "923166753715");
});

check("without a resolved number it still falls back to the jid", () => {
  const out = inboundMessage({ from: "971501234567@c.us", id: { _serialized: "x" }, type: "chat" });
  assert.equal(out.messages[0].from, "971501234567");
});

console.log(`\n  ${passed} checks passed`);
