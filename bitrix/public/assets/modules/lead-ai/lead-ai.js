/**
 * Lead AI — its own screen and its own folder (modules/lead-ai/).
 *
 * A CRM campaign sent with the popup's "Lead AI" box puts each chat it
 * reaches here instead of the main inbox (backend: apps/leadai). The server
 * leaves those chats out of the inbox list and sends their live events as
 * "leadai.*", which inbox.js ignores; core/realtime.js re-broadcasts every
 * frame on window as "wa:event", and this module listens there.
 *
 * Loaded by index.html as its own <script type="module"> and never imported
 * by inbox.js, so nothing in this folder can stop the main inbox starting.
 * It adds its own menu item, keeps an unread count on it, chimes for a reply,
 * shows the assistant's alerts (a booking, a hot lead, "on my way", a request
 * for a person...) wherever the agent is, and answers the inbox through
 * window.a7wa:
 *   openLeadAi(conversationId, { highlightMessageId })  a link to a Lead AI chat
 *   findLeadAiChat(waId)  New contact's "this customer already has a chat"
 */

import { debounce, el } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { notifyNewMessage } from "../../core/notifications.js";
import { asList, leadAiApi } from "./api.js";
import { contactName } from "./thread.js";
import { closeScreen, deliverToScreen, isScreenOpen, openChatId, openLeadAiScreen, resyncScreen } from "./screen.js";

let me = null;
let unreadChats = 0;
let socketReadyCount = 0;
const badges = new Set();

function open(conversationId, { highlightMessageId } = {}) {
  openLeadAiScreen({ conversationId, highlightMessageId, me, onUnreadChanged: setUnread });
}

async function findLeadAiChat(waId) {
  const digits = String(waId || "").replace(/\D/g, "");
  if (!digits) return null;
  const rows = asList(await leadAiApi.chats({ q: digits, limit: 10 }), "results");
  const match = rows.find((row) => {
    const own = String(row.contact?.wa_id || "");
    return own && (own.endsWith(digits) || digits.endsWith(own));
  });
  return match ? { id: match.id, number_id: match.number_id } : null;
}

window.a7wa = window.a7wa || {};
window.a7wa.openLeadAi = (conversationId, options = {}) => open(conversationId, options);
window.a7wa.findLeadAiChat = (waId) => findLeadAiChat(waId);

/* ------------------------------------------------------------ unread count */

function setUnread(count) {
  unreadChats = Math.max(0, Number(count) || 0);
  for (const badge of badges) {
    badge.textContent = unreadChats ? String(unreadChats) : "";
    badge.hidden = !unreadChats;
  }
  const dot = document.querySelector(".sidebar__menu-btn .lai-menu-dot");
  if (dot) dot.hidden = !unreadChats;
}

const refreshUnread = debounce(async () => {
  try {
    const payload = await leadAiApi.chats({ limit: 1 });
    if (typeof payload?.unread_chats === "number") setUnread(payload.unread_chats);
  } catch {
    /* the badge is a hint; the screen itself loads the truth */
  }
}, 600);

/* --------------------------------------------------------------- menu item */

/**
 * "Lead AI" in the hamburger menu, as its own section after the campaign
 * items. Injected here so inbox.js does not carry it; the menu is built when
 * the inbox mounts, which may be after this module loads.
 */
function injectMenuItem() {
  const menu = document.querySelector(".sidebar__menu");
  if (!menu) return false;
  if (menu.querySelector(".lai-menu-item")) return true;

  const badge = el("span.lai-menu-badge", { hidden: true });
  badges.add(badge);
  const heading = el("div.menu__section.lai-menu-section", {}, ["Lead AI"]);
  const item = el("button.btn.menu__item.lai-menu-item", { type: "button", onclick: () => open() }, [
    icon("smartphone", { size: 16 }),
    "Lead AI",
    badge,
  ]);

  // Before the first section heading that follows "Campaign", so the items
  // under Campaign (Excel campaigns, Linked phone agents) stay where they were.
  const children = [...menu.children];
  const campaign = children.find((node) => node.classList?.contains("menu__item") && node.textContent.trim() === "Campaign");
  const from = campaign ? children.indexOf(campaign) + 1 : 0;
  const nextSection = children.slice(from).find((node) => node.classList?.contains("menu__section"));
  if (nextSection) nextSection.before(heading, item);
  else menu.append(heading, item);

  // A dot on the menu button, since the item itself is hidden in the menu.
  const menuButton = document.querySelector(".sidebar__menu-btn");
  if (menuButton && !menuButton.querySelector(".lai-menu-dot")) {
    menuButton.append(el("span.lai-menu-dot", { hidden: true, title: "Unread Lead AI chats" }));
  }
  setUnread(unreadChats);
  return true;
}

let watching = false;

function watchMenu() {
  if (injectMenuItem() || watching) return;
  // The inbox builds its menu when it mounts, which may be after this module
  // loads; watch until it exists, then stop (the menu is built once).
  watching = true;
  const observer = new MutationObserver(() => {
    if (injectMenuItem()) {
      observer.disconnect();
      watching = false;
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
}

/* ------------------------------------------------------------------ alerts */

/*
 * "leadai.alert" goes to one agent: the chat's owner and the CRM record's
 * responsible person. It arrives whatever screen is open, so the stack hangs
 * off <body>, on the top layer where the browser has one (popover="manual":
 * above every dialog, and never dismissed by a click elsewhere), and as a
 * fixed layer above the panel's own dialogs where it has not.
 */

// An urgent alert stays three times as long; both wait while the agent hovers or focuses them.
const ALERT_MS = { normal: 10000, high: 30000 };
// After the pointer or focus leaves an alert, it stays at least this long.
const ALERT_RESUME_MS = 4000;
const ALERT_MAX = 4;
const seenAlerts = new Set();
// A customer's message can arrive twice: on the chat owner's own channel and on
// the desk's (an owner with Lead AI access, apps/leadai/lane.py). It chimes once.
const seenMessages = new Set();

const canLayer = typeof HTMLElement !== "undefined" && "popover" in HTMLElement.prototype;

function alertHost() {
  let host = document.querySelector(".lai-alerts");
  if (!host) {
    host = el("div.lai-alerts", { role: "region", "aria-label": "Lead AI alerts" });
    if (canLayer) host.setAttribute("popover", "manual");
    document.body.append(host);
  }
  if (canLayer && host.hasAttribute("popover")) {
    try {
      if (!host.matches(":popover-open")) host.showPopover();
    } catch {
      /* still shown, as the fixed layer lead-ai.css gives it */
    }
  }
  return host;
}

/** Opens the chat an alert is about, where it lives now. */
function openAlertChat(alert) {
  const id = alert?.conversation_id;
  if (!id) return;
  if (alert.lead_ai) {
    open(id);
    return;
  }
  // Back in the main inbox: it opens there, and this screen would cover it.
  closeScreen();
  window.a7wa?.openConversation?.(id);
}

function showAlert(alert) {
  if (!alert || typeof alert !== "object") return;
  const key = alert.id != null ? String(alert.id) : "";
  if (key) {
    if (seenAlerts.has(key)) return;
    seenAlerts.add(key);
    if (seenAlerts.size > 200) seenAlerts.delete(seenAlerts.values().next().value);
  }
  const high = alert.priority === "high";
  const title = String(alert.title || "").trim() || "Lead AI alert";
  const text = String(alert.text || "").trim();
  const openable = Boolean(alert.conversation_id);

  let timer = null;
  let deadline = 0;
  let remaining = 0;
  let gone = false;

  const node = el("div.lai-alert", { class: high ? "lai-alert--high" : "", role: high ? "alert" : "status" }, [
    el("button.lai-alert__main", {
      type: "button",
      title: openable ? "Open the chat" : null,
      onclick: () => {
        dismiss();
        openAlertChat(alert);
      },
    }, [
      el("span.lai-alert__icon", { "aria-hidden": "true" }, [icon(high ? "alert" : "bell", { size: 16 })]),
      el("span.lai-alert__body", {}, [
        el("span.lai-alert__kicker", {}, [high ? "Lead AI · urgent" : "Lead AI"]),
        el("span.lai-alert__title", {}, [title]),
        text ? el("span.lai-alert__text", {}, [text]) : null,
        openable ? el("span.lai-alert__open", {}, ["Open chat"]) : null,
      ]),
    ]),
    el("button.lai-alert__close", { type: "button", title: "Dismiss", "aria-label": "Dismiss", onclick: () => dismiss() }, [
      icon("close", { size: 14 }),
    ]),
  ]);

  function arm(ms) {
    clearTimeout(timer);
    deadline = Date.now() + ms;
    timer = setTimeout(dismiss, ms);
  }

  function hold() {
    if (gone || !timer) return;
    clearTimeout(timer);
    timer = null;
    remaining = Math.max(deadline - Date.now(), 0);
  }

  function release() {
    if (gone || timer) return;
    arm(Math.max(remaining, ALERT_RESUME_MS));
  }

  function dismiss() {
    if (gone) return;
    gone = true;
    clearTimeout(timer);
    node.classList.add("is-leaving");
    setTimeout(() => node.remove(), 220);
  }

  // Held while the agent is reading it, with the pointer or the keyboard.
  node.addEventListener("mouseenter", hold);
  node.addEventListener("mouseleave", release);
  node.addEventListener("focusin", hold);
  node.addEventListener("focusout", (event) => {
    if (!node.contains(event.relatedTarget)) release();
  });

  const host = alertHost();
  host.prepend(node);
  while (host.children.length > ALERT_MAX) host.lastElementChild?.remove();
  arm(high ? ALERT_MS.high : ALERT_MS.normal);

  // The same chime as a customer's reply, and a browser notification when
  // the panel is not in front (both follow the agent's sound and desktop switches).
  notifyNewMessage({
    contactName: `Lead AI · ${title}`,
    messageText: text || title,
    conversationId: alert.conversation_id,
    onClick: () => openAlertChat(alert),
  });
}

/* ------------------------------------------------------------------- live */

window.addEventListener("wa:event", (event) => {
  const { event: name, data } = event.detail || {};
  if (!name) return;

  // The server says "ready" on every (re)connect; after a gap, refetch.
  if (name === "ready") {
    socketReadyCount += 1;
    if (socketReadyCount > 1) {
      refreshUnread();
      resyncScreen();
    }
    return;
  }

  if (isScreenOpen()) deliverToScreen(name, data);
  if (!String(name).startsWith("leadai.")) return;

  if (name === "leadai.alert") {
    showAlert(data);
    return;
  }

  if (name === "leadai.message.new") {
    const message = data?.message;
    const conversation = data?.conversation;
    // Only a customer's message adds to the unread count. Our own sends do
    // not, and a campaign makes hundreds of them.
    if (message?.direction !== "in") return;
    if (message.id != null) {
      const key = String(message.id);
      if (seenMessages.has(key)) return;
      seenMessages.add(key);
      if (seenMessages.size > 200) seenMessages.delete(seenMessages.values().next().value);
    }
    const reading =
      isScreenOpen() &&
      String(openChatId()) === String(conversation?.id ?? message?.conversation_id) &&
      document.visibilityState === "visible";
    if (!reading) {
      notifyNewMessage({
        contactName: `Lead AI · ${contactName(conversation)}`,
        messageText: message.body || "New message",
        conversationId: conversation?.id,
        onClick: () => open(conversation?.id),
      });
    }
    refreshUnread();
    return;
  }
  // A chat read, moved here or reassigned. Receipts, "the AI is writing", its
  // state and the closing-window warning leave the count as it was.
  if (String(name).startsWith("leadai.conversation.")) refreshUnread();
});

function start() {
  me = window.a7wa?.getMe?.() || me;
  watchMenu();
  refreshUnread();
}

window.addEventListener("wa:ready", (event) => {
  me = event.detail?.me || me;
  start();
});

// If the inbox was already up when this module arrived.
if (window.a7wa?.getMe) start();
