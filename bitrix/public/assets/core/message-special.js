/**
 * Read-only cards for inbound contact / album / pin messages.
 *
 * Kept out of inbox.js — that file is edited by multiple agents at once.
 * Gateway cannot send contact cards; these are display-only.
 */

import { el, toast } from "./dom.js";
import { icon } from "./icons.js";

function copyPhone(phone) {
  const text = String(phone || "").trim();
  if (!text) return;
  const done = () => toast(`Copied ${text}`);
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => toast("Could not copy the number", "err"));
    return;
  }
  toast("Could not copy the number", "err");
}

function contactsCard(message) {
  const cards = Array.isArray(message.contacts) ? message.contacts : [];
  if (!cards.length) return null;

  return el("div.msg__special.msg__contact-card", {}, [
    el("div.msg__special-title", {}, [icon("users", { size: 14 }), " Contact"]),
    ...cards.map((card) =>
      el("div.msg__contact-row", {}, [
        el("div.msg__contact-name", {}, [card.name || "Contact"]),
        ...(card.phones || []).map((phone) =>
          el("button.msg__contact-phone", {
            type: "button",
            title: "Copy number",
            onclick: (event) => {
              event.preventDefault();
              event.stopPropagation();
              copyPhone(phone);
            },
          }, [icon("copy", { size: 12 }), phone])
        ),
      ])
    ),
  ]);
}

function albumCard(message) {
  const count = Number(message.album_count) || 0;
  if (!count) return null;
  return el("div.msg__special.msg__album-card", {}, [
    icon("image", { size: 14 }),
    `${count} photo${count === 1 ? "" : "s"}`,
  ]);
}

function pinCard(message) {
  const pinned = message.pinned || {};
  const preview = String(pinned.body || "").trim();
  return el("div.msg__special.msg__pin-card", {}, [
    el("div.msg__special-title", {}, [icon("pin", { size: 14 }), " Pinned message"]),
    preview ? el("div.msg__pin-preview", {}, [preview]) : null,
  ]);
}

/** Card for contacts / album / pin, or null so the bubble can fall back. */
export function specialMessageNode(message) {
  const kind = String(message?.kind || "").toLowerCase();
  if (kind === "contacts" || (Array.isArray(message?.contacts) && message.contacts.length)) {
    return contactsCard(message) || el("div.msg__special", {}, ["Contact card"]);
  }
  if (kind === "album") {
    return albumCard(message) || el("div.msg__special.msg__album-card", {}, ["Photo album"]);
  }
  if (kind === "pinned_message" || message?.pinned) {
    return pinCard(message);
  }
  return null;
}
