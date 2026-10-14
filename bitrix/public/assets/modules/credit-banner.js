/**
 * Red banner while sends are held; amber while credit is low.
 * Own module so the inbox and Lead AI screens stay untouched.
 */

import { apiFetch } from "../core/bitrix-sso.js";
import { el } from "../core/dom.js";

const OUT = "WhatsApp credit is out — messages are not going";
const LOW = "WhatsApp credit is low";

function banner() {
  return document.querySelector(".crb-banner");
}

function show(kind, text) {
  const node = banner();
  if (node) {
    node.className = `crb-banner crb-${kind}`;
    node.textContent = text;
    return;
  }
  document.body.prepend(
    el("div", { class: `crb-banner crb-${kind}`, role: "status", text })
  );
}

function hide() {
  const node = banner();
  if (node) node.remove();
}

async function paint() {
  try {
    const data = await apiFetch("/api/gateway/credit/");
    if (data && data.out) show("out", OUT);
    else if (data && data.low) show("low", LOW);
    else hide();
  } catch {
    /* A signed-out panel has nothing to warn. */
  }
}

paint();
setInterval(paint, 60 * 1000);
