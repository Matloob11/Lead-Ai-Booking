import { inboundMessage, inboundReaction, envelope } from "../src/inbound/normalise.js";

const number = "923001234567";
const out = {
  text: envelope(inboundMessage({
    from: "971509998887@c.us",
    id: { _serialized: "false_971509998887@c.us_QRPROBE1" },
    timestamp: Math.floor(Date.now() / 1000),
    type: "chat",
    body: "Sent from the QR channel",
  }, { contactName: "QR Probe" }), number),

  image: envelope(inboundMessage({
    from: "971509998887@c.us",
    id: { _serialized: "false_971509998887@c.us_QRPROBE2" },
    timestamp: Math.floor(Date.now() / 1000),
    type: "image",
    body: "floorplan",
  }, { contactName: "QR Probe",
       media: { id: "m1", mimetype: "image/jpeg", filelink: "https://gsauth.com/x.jpg", sha256: "abc" } }), number),

  reply: envelope(inboundMessage({
    from: "971509998887@c.us",
    id: { _serialized: "false_971509998887@c.us_QRPROBE3" },
    timestamp: Math.floor(Date.now() / 1000),
    type: "chat",
    body: "quoting the first one",
    hasQuotedMsg: true,
  }, { quotedId: "false_971509998887@c.us_QRPROBE1" }), number),

  reaction: envelope(inboundReaction({
    senderId: "971509998887@c.us",
    id: { _serialized: "r-QRPROBE" },
    msgId: { _serialized: "false_971509998887@c.us_QRPROBE1" },
    reaction: "\u{1F44D}",
    timestamp: Math.floor(Date.now() / 1000),
  }), number),
};
console.log(JSON.stringify(out));
