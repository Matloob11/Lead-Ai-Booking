/**
 * Red banner while the gateway wallet is too low to send.
 * Own module so the inbox and Lead AI screens stay untouched.
 */

import { apiFetch } from "../core/bitrix-sso.js";
import { el } from "../core/dom.js";

const TEXT = "WhatsApp credit is out — messages are not going";

function banner() {
  return document.querySelector(".crb-banner");
}

function show() {
  if (banner()) return;
  document.body.prepend(el("div", { class: "crb-banner", role: "status", text: TEXT }));
}

function hide() {
  const node = banner();
  if (node) node.remove();
}

async function paint() {
  try {
    const data = await apiFetch("/api/gateway/credit/");
    if (data && data.out) show();
    else hide();
  } catch {
    /* A signed-out panel has nothing to warn. */
  }
}

paint();
setInterval(paint, 60 * 1000);
