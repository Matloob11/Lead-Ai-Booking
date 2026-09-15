/**
 * Template buttons and button-reply tags for the Official API thread.
 * Kept out of inbox.js — that file is edited by multiple agents at once.
 */

import { el } from "./dom.js";
import { icon } from "./icons.js";

const BUTTON_LABEL = {
  URL: "Link",
  PHONE_NUMBER: "Call",
  QUICK_REPLY: "Reply",
};

function buttonKindIcon(type) {
  if (type === "URL") return icon("globe", { size: 14 });
  if (type === "PHONE_NUMBER") return icon("phone", { size: 14 });
  return icon("reply", { size: 14 });
}

/** Small tag above a customer's tapped button text. */
export function buttonReplyTag(kind) {
  const label = kind === "interactive" ? "Menu reply" : "Button reply";
  return el("div.msg__button-reply-tag", {}, [icon("reply", { size: 12 }), label]);
}

/** Footer line inside a template bubble. */
export function templateFooterNode(message) {
  const footer = String(message.template_footer || "").trim();
  if (!footer) return null;
  return el("div.msg__template-footer", {}, [footer]);
}

/** WhatsApp-style button row — sits under the green bubble, display-only. */
export function templateButtonsRow(message) {
  const buttons = message.template_buttons || [];
  if (!buttons.length) return null;

  const rows = buttons.slice(0, 3).map((button) =>
    el("div.msg__template-btn", { title: BUTTON_LABEL[button.type] || "Button" }, [
      buttonKindIcon(button.type),
      el("span", {}, [button.text || "Button"]),
    ])
  );

  if (buttons.length > 3) {
    rows.push(
      el("div.msg__template-btn msg__template-btn--more", {}, [
        icon("reply", { size: 14 }),
        el("span", {}, ["See all options"]),
      ])
    );
  }

  return el("div.msg__template-btns", {}, rows);
}
