/**
 * The panel for the QR-linked channel — laid out like the inbox it sits beside:
 * chats down the left, the open conversation filling the right, both scrolling
 * on their own inside whatever height the frame gives us.
 *
 * Plain ES modules, no framework, no build. The main panel is built the same
 * way and this one is deployed the same way, by copying the folder.
 *
 * Nothing a customer wrote is ever put through innerHTML. Every message body,
 * contact name and group subject on this screen was typed by somebody outside
 * the company, so it is only ever a text node.
 */

import { icon, initials, hueFor } from "./icons.js";
// The lightbox, reactions, search, stars, forwarding and the contact panel. It
// owns all of that itself and takes five one-line hooks from this file, so the
// two can be edited at the same time without meeting in the middle.
import {
  decorateBubble,
  installThreadExtras,
  notifyThreadPainted,
  threadHeadExtras,
  voiceNote,
} from "./thread-extras.js";
import { createComposer } from "./composer.js";
// Who works which phone, and how those phones are behaving. It also says why
// the panel is empty when it is — installed on import, so this is one line for
// both halves of it.
import { openPhonesAdmin } from "./phones-admin.js";
// The band across the top warning that a number is being used the way banned
// numbers are used. Its own module, and its own file, for the same reason.
import { installSafetyBanner } from "./safety.js";
// Starting a conversation, and the screens that say what starting one costs.
// Same arrangement again: it owns its own dialogs and takes one-line hooks.
import {
  filterStrip,
  installNewChat,
  kindLabel,
  newChatButton,
  passesFilters,
  riskChipFor,
} from "./newchat.js";

const POLL_CHAT_MS = 5000;   // no socket on this service; the list is polled
const POLL_QR_MS = 3000;     // the code itself rotates roughly every 20 seconds
const MAX_BODY = 4096;
const PAGE = 40;             // messages per request, going back through a thread

/* ----------------------------------------------------------------- helpers */

/** el("div.row", {onclick}, [child, "text"]) → HTMLElement. */
function el(spec, props = {}, children = []) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");

  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      node.className = [node.className, value].filter(Boolean).join(" ");
    } else if (key in node && key !== "list") {
      node[key] = value;
    } else {
      node.setAttribute(key, value === true ? "" : value);
    }
  }

  for (const child of [children].flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const clear = (node) => (node.replaceChildren(), node);

/**
 * Where this panel's own API lives, whatever it is being served under.
 *
 * On the VPS nginx publishes the service at /qr/, so an absolute "/api/…"
 * would leave for the host root and land on the Django backend instead — a
 * different application that knows nothing about these routes. Resolving
 * against the document's own base keeps every call inside whatever prefix the
 * page was reached by, including plain localhost during development.
 */
const apiBase = new URL("./", document.baseURI);

/** Re-bases a path the server handed us, which may already be absolute. */
const onApi = (path) => new URL(String(path).replace(/^\//, ""), apiBase).href;

async function api(path, { method = "GET", body } = {}) {
  const init = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const response = await fetch(onApi(path), init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    // The server's own words are worth more than a status code here: refusing
    // a Business Platform number comes back as a sentence explaining why.
    throw new Error(payload?.error || payload?.detail || `${method} ${path} → HTTP ${response.status}`);
  }
  return payload;
}

/** Collections come back bare or wrapped, depending on the route. */
function asList(payload, key) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const candidate of [key, "results", "items", "data"]) {
    if (candidate && Array.isArray(payload[candidate])) return payload[candidate];
  }
  return [];
}

const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const DAY = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

/** Time today, date before that — the usual chat-list shorthand. */
function stamp(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear();
  return sameDay ? TIME.format(date) : DAY.format(date);
}

function fullStamp(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  const value = n / 1024 ** i;
  return `${value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}

const withPlus = (digits) => (digits ? `+${String(digits).replace(/\D/g, "")}` : "");

/**
 * One shape for a session, whichever the server sends.
 *
 * /api/sessions returns camelCase (phoneNumber, lastError, lastSeenAt) while
 * /api/sessions/:id/qr returns snake_case (qr_data_url) — the two disagree
 * inside the same service. Reading both keeps the panel working through that.
 */
function normaliseSession(row) {
  if (!row) return null;
  return {
    ...row,
    id: row.id,
    label: row.label || "",
    status: row.status || "",
    phone_number: row.phone_number ?? row.phoneNumber ?? "",
    last_error: row.last_error ?? row.lastError ?? "",
    last_seen_at: row.last_seen_at ?? row.lastSeenAt ?? null,
    qr_data_url: row.qr_data_url ?? row.qrDataUrl ?? "",
  };
}

const sessionName = (s) => s.label || withPlus(s.phone_number) || `Phone #${s.id}`;

/* ----------------------------------------------------------------- dialogs */

/**
 * Asking a question without window.prompt or window.confirm.
 *
 * Chrome refuses both inside a cross-origin iframe, and this panel is served
 * from a different host than the Bitrix page that frames it. On localhost the
 * buttons worked; inside Bitrix prompt() returned null and confirm() returned
 * false, so "Link a phone" and "Disconnect" both did nothing at all and said
 * nothing about why.
 */
function dialog({ title, body, actions = [], wide = false }) {
  const box = el("div.dlg__box", { class: wide ? "dlg__box--wide" : "" }, [
    el("div.dlg__head", {}, [
      el("h2.dlg__title", {}, [title]),
      el("button.dlg__x", { type: "button", title: "Close" }, [icon("close", { size: 16 })]),
    ]),
    body,
    actions.length ? el("div.dlg__actions", {}, actions) : null,
  ]);
  const backdrop = el("div.dlg", {}, [box]);

  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
  };
  const dismiss = () => {
    close();
    backdrop.dispatchEvent(new CustomEvent("dismiss"));
  };
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismiss();
    }
  };

  box.querySelector(".dlg__x").addEventListener("click", dismiss);
  backdrop.addEventListener("click", (event) => event.target === backdrop && dismiss());
  document.addEventListener("keydown", onKey, true);
  document.body.append(backdrop);
  return { node: backdrop, box, close };
}

/** @returns {Promise<string|null>} the text, or null if it was dismissed. */
function askText({ title, label, placeholder = "", confirmLabel = "OK" }) {
  return new Promise((resolve) => {
    const input = el("input.dlg__input", { type: "text", placeholder, maxlength: "120" });
    const ok = el("button.btn", { type: "button" }, [confirmLabel]);
    const cancel = el("button.btn.btn--ghost", { type: "button" }, ["Cancel"]);

    const d = dialog({
      title,
      body: el("label.dlg__field", {}, [el("span", {}, [label]), input]),
      actions: [cancel, ok],
    });

    const finish = (value) => {
      d.close();
      resolve(value);
    };
    ok.addEventListener("click", () => finish(input.value));
    cancel.addEventListener("click", () => finish(null));
    d.node.addEventListener("dismiss", () => resolve(null));
    input.addEventListener("keydown", (event) => event.key === "Enter" && finish(input.value));
    queueMicrotask(() => input.focus());
  });
}

/** @returns {Promise<boolean>} */
function askConfirm({ title, message, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const ok = el("button.btn", { type: "button", class: danger ? "btn--danger" : "" }, [confirmLabel]);
    const cancel = el("button.btn.btn--ghost", { type: "button" }, ["Cancel"]);
    const d = dialog({ title, body: el("p.dlg__text", {}, [message]), actions: [cancel, ok] });

    const finish = (value) => {
      d.close();
      resolve(value);
    };
    ok.addEventListener("click", () => finish(true));
    cancel.addEventListener("click", () => finish(false));
    d.node.addEventListener("dismiss", () => resolve(false));
    queueMicrotask(() => ok.focus());
  });
}

/* ------------------------------------------------------------------- theme */

/**
 * Follows the panel that frames this one.
 *
 * The inbox carries its theme on <body data-wa-theme>, and this page is a
 * separate document, so nothing inherits. It is framed by the inbox, which is
 * on the same origin, so the attribute can simply be read — through however
 * many frames deep it sits, falling back to the operating system's preference
 * when the chain is cross-origin and unreadable.
 */
function applyTheme() {
  let theme = "";
  try {
    for (let frame = window, hops = 0; frame !== frame.parent && hops < 4; hops += 1) {
      frame = frame.parent;
      theme = frame.document?.body?.dataset?.waTheme || theme;
    }
  } catch {
    // A cross-origin ancestor. Nothing to read, and nothing to fix.
  }

  if (!theme && window.matchMedia?.("(prefers-color-scheme: dark)").matches) theme = "glass-dark";
  if (theme) document.body.dataset.waTheme = theme;
}

/* ------------------------------------------------------------------ status */

const STATUS = {
  ready: { chip: "chip--ok", text: "Ready" },
  authenticated: { chip: "chip--warn", text: "Authenticated" },
  qr: { chip: "chip--warn", text: "Waiting for a scan" },
  initialising: { chip: "chip--plain", text: "Starting up" },
  disconnected: { chip: "chip--err", text: "Disconnected" },
  banned: { chip: "chip--err", text: "Banned" },
};

const statusOf = (value) => STATUS[value] || { chip: "chip--plain", text: value || "Unknown" };

/* ------------------------------------------------------------------- state */

const root = document.getElementById("root");

const state = {
  me: { agent_id: null, is_admin: false },
  sessions: [],
  phoneFilter: "",        // "" is every phone
  conversations: [],
  conversationId: null,
  messages: [],
  canLoadOlder: false,
  search: "",
  listError: "",
  threadError: "",
};

let poller = null;

const sessionById = (id) => state.sessions.find((s) => String(s.id) === String(id)) || null;
const activeConversation = () =>
  state.conversations.find((c) => String(c.id) === String(state.conversationId)) || null;

/* ---------------------------------------------------------------- the shell */

const ui = {
  phoneSelect: el("select.field.side__phones"),
  search: el("input.side__search", { type: "search", placeholder: "Search chats" }),
  convs: el("div.convs"),
  importing: el("div.side__importing", { hidden: true }),
  thread: el("section.thread"),
};

const layout = el("div.app", {}, [
  el("aside.side", {}, [
    el("div.side__top", {}, [
      el("div.side__title", {}, [icon("phone", { size: 16 }), "Linked phones"]),
      el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: openPhones }, [
        icon("link", { size: 13 }),
        "Manage",
      ]),
      // Messaging somebody who has not written first — the one action on this
      // screen that can get a number banned, so it carries its own warnings.
      newChatButton(),
    ]),
    el("div.side__filters", {}, [
      ui.phoneSelect,
      // The magnifier lives inside the field rather than beside it, so the row
      // stays one control.
      el("div.side__search-wrap", {}, [icon("search", { size: 15 }), ui.search]),
    ]),
    // Unread / mine / Safety — "what have I not dealt with" is a different
    // question from the search box's "find me this chat".
    filterStrip(),
    ui.importing,
    ui.convs,
  ]),
  ui.thread,
]);

ui.phoneSelect.addEventListener("change", () => {
  state.phoneFilter = ui.phoneSelect.value;
  state.conversationId = null;
  state.messages = [];
  renderThread();
  refresh();
});

ui.search.addEventListener("input", () => {
  state.search = ui.search.value.trim().toLowerCase();
  paintConversations();
});

/* ------------------------------------------------------------------ loading */

async function loadSessions() {
  try {
    state.sessions = asList(await api("api/sessions"), "sessions").map(normaliseSession);
  } catch (error) {
    state.listError = error.message;
  }
}

/**
 * Whether this agent may link and unlink phones.
 *
 * Asked once at boot. A failure leaves the answer at "no", which shows fewer
 * buttons than it should rather than more — and the ones it would hide are the
 * ones the server refuses anyway.
 */
async function loadMe() {
  try {
    state.me = await api("api/me");
  } catch {}
}

/** "about 4 minutes", "less than a minute", "about 1 hour 10 min". */
function humanDuration(ms) {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return "less than a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `about ${hours} hour${hours === 1 ? "" : "s"}${rest ? ` ${rest} min` : ""}`;
}

/**
 * Where each phone's import was when this page first saw it.
 *
 * The rate is measured from here rather than from the run's own start, and that
 * is the whole point. Everything before the first chat — connecting, and
 * reading a list of four hundred chats out of the handset — lands inside the
 * elapsed time of chat number one, so dividing by the run's start says "about
 * 2 hours 21 min" for a phone that is nine minutes from finishing. Watching
 * the counter move instead measures only the part that is still to happen.
 */
const importSeen = new Map();

/** Seconds per chat, measured on this phone, or null until it is worth having. */
function ratePerChat(session) {
  const key = String(session.id);
  const done = session.history?.chatsDone || 0;
  const now = Date.now();
  const seen = importSeen.get(key);

  // First sight, or a new run that started the count again.
  if (!seen || done < seen.done) {
    importSeen.set(key, { done, at: now });
    return null;
  }

  const chats = done - seen.done;
  const elapsed = now - seen.at;
  // Deliberately not updated here: this is called several times per repaint,
  // and moving the mark on each call would measure a fraction of a second.
  return chats >= 3 && elapsed >= 10_000 ? elapsed / chats : null;
}

/**
 * How much longer the import has to run.
 *
 * Measured rather than guessed at: chats differ enormously — one holds four
 * messages and the next holds nine thousand — so a fixed per-chat figure would
 * be wrong for every phone.
 *
 * "" until there is something worth dividing by. A countdown that opens at two
 * hours and drops to nine minutes is worse than no countdown.
 */
function etaFor(session) {
  const { chatsDone: done, chatsTotal: total } = session.history || {};
  if (!total || done >= total) return "";

  const perChat = ratePerChat(session);
  return perChat ? humanDuration(perChat * (total - done)) : "";
}

/** How far along, 0..1, or null while the total is still unknown. */
function historyFraction(history) {
  const { chatsDone: done, chatsTotal: total } = history || {};
  if (!total) return null;
  return Math.min(1, done / total);
}

/**
 * What the history import is doing, in a sentence, or "" when there is nothing
 * to say. A phone that finished importing months ago does not need to mention
 * it every time the panel repaints.
 */
function historyNote(session) {
  const h = session.history || {};

  // An import only happens over a live connection, so a phone that is not
  // connected is not importing however recently its row said it was. The row
  // lags: the run notices the phone has gone at its next chat, and until then
  // the card claimed to be reading chats off a phone that had been disconnected
  // for a quarter of an hour.
  const live = session.status === "ready";

  if (h.status === "running" || h.status === "pending") {
    if (!live) {
      return h.chatsTotal
        ? `Import paused at ${h.chatsDone} of ${h.chatsTotal} chats — it continues when this phone reconnects`
        : "Import paused — it continues when this phone reconnects";
    }
    if (h.status === "pending" || !h.chatsTotal) return "Reading the chat list…";
    const eta = etaFor(session);
    return `Importing chats — ${h.chatsDone} of ${h.chatsTotal}${eta ? `, ${eta} left` : ""}`;
  }

  if (h.status === "failed") return `The import stopped: ${h.error || "reason unknown"}`;
  return "";
}

/** Whether to draw a spinner: something is actually moving right now. */
const isImporting = (session) => {
  const status = (session.history || {}).status;
  return session.status === "ready" && (status === "running" || status === "pending");
};

async function loadConversations() {
  const query = state.phoneFilter ? `?session_id=${encodeURIComponent(state.phoneFilter)}` : "";
  try {
    const payload = await api(`api/conversations${query}`);
    // Sorted here rather than trusted from the wire: the list is only useful
    // newest-first, and the route does not promise an order.
    state.conversations = asList(payload, "conversations").sort(
      (a, b) => new Date(b.last_message_at || 0) - new Date(a.last_message_at || 0)
    );
    state.listError = "";
  } catch (error) {
    state.listError = error.message;
  }
}

/** Oldest first, which is reading order. */
const inReadingOrder = (rows) =>
  rows.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));

async function loadMessages(id) {
  try {
    const payload = await api(`api/conversations/${id}/messages?limit=${PAGE}`);
    // Sorted here for the same reason the conversations are: the route does not
    // promise an order, and a thread that renders backwards is worse than one
    // that loads a moment later.
    state.messages = inReadingOrder(asList(payload, "messages"));
    // A full page means there is probably another one behind it.
    state.canLoadOlder = state.messages.length >= PAGE;
    state.threadError = "";
  } catch (error) {
    state.threadError = error.message;
    state.messages = [];
    state.canLoadOlder = false;
  }
}

/**
 * The page before the one on screen.
 *
 * Worth having now that a linked phone's own history is imported: a chat can
 * hold six months of conversation, and until this the panel could only ever
 * show the last forty messages of it — the import would have been real and
 * invisible at the same time.
 */
async function loadOlderMessages() {
  const oldest = state.messages[0];
  if (!oldest || !state.conversationId) return 0;

  const payload = await api(
    `api/conversations/${state.conversationId}/messages?limit=${PAGE}&before=${oldest.id}`
  );
  const older = inReadingOrder(asList(payload, "messages"));
  state.canLoadOlder = older.length >= PAGE;
  state.messages = [...older, ...state.messages];
  return older.length;
}

async function refresh({ keepScroll = true } = {}) {
  await Promise.all([loadSessions(), loadConversations()]);
  renderPhoneSelect();
  paintConversations();
  if (state.conversationId) {
    await loadMessages(state.conversationId);
    // Only the messages: a poll must not take the composer with it.
    paintMessages({ keepScroll });
    // Whatever arrived during this poll landed in a thread somebody has open.
    await markRead(state.conversationId);
  }
}

/**
 * Clears the badge on the chat that is open in front of somebody.
 *
 * Only while this page is on screen. The panel polls whether or not anyone is
 * looking at it, so a chat left open in a background tab would otherwise have
 * every message that arrived overnight marked read before the agent saw a
 * single one — which is exactly what went wrong in the main inbox, and for
 * exactly this reason.
 *
 * The local count goes first so the number disappears the moment the chat is
 * opened rather than at the next poll five seconds later. The server's answer
 * is not read back: the next poll carries the real count, and if this call
 * failed that count is the honest one to show.
 */
async function markRead(id) {
  if (!id || document.visibilityState !== "visible") return;

  const conversation = state.conversations.find((c) => String(c.id) === String(id));
  if (!conversation?.unread_count) return;

  conversation.unread_count = 0;
  paintConversations();

  try {
    await api(`api/conversations/${id}/read`, { method: "POST" });
  } catch (error) {
    console.warn("[wa-qr] could not mark the chat read:", error.message);
  }
}

/* ----------------------------------------------------------------- sidebar */

function renderPhoneSelect() {
  const chosen = state.phoneFilter;
  clear(ui.phoneSelect).append(el("option", { value: "" }, ["All phones"]));
  for (const session of state.sessions) {
    const look = statusOf(session.status);
    ui.phoneSelect.append(
      el("option", { value: String(session.id) }, [
        `${sessionName(session)}${session.status === "ready" ? "" : ` — ${look.text}`}`,
      ])
    );
  }
  // A phone that has just been removed leaves the filter pointing at nothing.
  ui.phoneSelect.value = state.sessions.some((s) => String(s.id) === String(chosen)) ? chosen : "";
  state.phoneFilter = ui.phoneSelect.value;

  // Said out loud while it runs, because it takes minutes and a chat list that
  // is still filling in looks like a chat list that is missing chats.
  const busy = state.sessions.filter(isImporting);
  ui.importing.hidden = !busy.length;
  if (busy.length) {
    clear(ui.importing).append(
      ...busy.map((session) =>
        el("div.side__importing-row", {}, [`${sessionName(session)}: ${historyNote(session)}`])
      ),
      el("div.side__importing-note", {}, ["Older chats appear as they are read."])
    );
  }
}

function conversationTitle(conversation) {
  return (
    conversation.subject ||
    // What the server already resolved: display name, else profile name, else
    // the number. The separate fields are read too in case it stops doing that.
    conversation.contact?.name ||
    conversation.contact?.display_name ||
    conversation.contact?.profile_name ||
    withPlus(conversation.contact?.wa_id) ||
    `Chat #${conversation.id}`
  );
}

const conversationWaId = (conversation) => conversation.contact?.wa_id || conversation.wa_id || "";

function visibleConversations() {
  // The strip's own filters first, then the text search.
  const rows = state.conversations.filter(passesFilters);
  if (!state.search) return rows;
  return rows.filter((c) =>
    `${conversationTitle(c)} ${c.last_message_preview || ""}`.toLowerCase().includes(state.search)
  );
}

function paintConversations() {
  clear(ui.convs);

  if (state.listError) ui.convs.append(el("div.alert", {}, [state.listError]));

  const rows = visibleConversations();
  if (!rows.length) {
    ui.convs.append(
      el("div.empty", {}, [
        state.conversations.length
          ? "No chat matches that."
          : "No chats yet. They appear as messages arrive.",
      ])
    );
    return;
  }

  for (const conversation of rows) {
    const phone = sessionById(conversation.session_id);
    const title = conversationTitle(conversation);
    ui.convs.append(
      el(
        "button.conv",
        {
          type: "button",
          class: [
            String(conversation.id) === String(state.conversationId) ? "is-active" : "",
            conversation.unread_count ? "has-unread" : "",
          ]
            .filter(Boolean)
            .join(" "),
          onclick: () => selectConversation(conversation.id),
        },
        [
          avatarFor(conversation, title),
          el("div.conv__body", {}, [
            el("div.conv__line", {}, [
              el("span.conv__name", {}, [
                conversation.is_group ? el("span.chip--group", {}, ["Group"]) : null,
                el("span", {}, [title]),
              ]),
              el("span.conv__when", {}, [stamp(conversation.last_message_at)]),
            ]),
            el("div.conv__line", {}, [
              el("span.conv__last", {}, [
                // A photo with no caption reads as "Photo", not "[image]" —
                // and the kinds this panel does not model yet say so in words
                // rather than as "[unknown]".
                conversation.last_message_preview || kindLabel(conversation.last_message_kind),
              ]),
              conversation.unread_count
                ? el("span.conv__unread", {}, [String(conversation.unread_count)])
                : null,
            ]),
            // Only worth naming while more than one phone is in the list.
            !state.phoneFilter && phone
              ? el("div.conv__phone", {}, [icon("phone", { size: 11 }), sessionName(phone)])
              : null,
          ]),
        ]
      )
    );
  }
}

/**
 * The disc beside a chat.
 *
 * Keyed on the wa_id rather than the name: a contact who is saved later stops
 * being "+971…" and becomes "Ahmed", and the colour should not change with it.
 * A group is the one case that skips the colour entirely — it is not a person.
 */
function avatarFor(conversation, title, { small = false } = {}) {
  const classes = ["div.avatar", small ? "avatar--sm" : "", conversation.is_group ? "avatar--group" : ""]
    .filter(Boolean)
    .join(".");

  if (conversation.is_group) {
    return el(classes, { "aria-hidden": "true" }, [icon("users", { size: small ? 15 : 17 })]);
  }
  const key = conversationWaId(conversation) || title;
  return el(classes, { style: `--hue: ${hueFor(key)}`, "aria-hidden": "true" }, [initials(title)]);
}

async function selectConversation(id) {
  state.conversationId = id;
  state.messages = [];
  renderThread();
  paintConversations();
  await loadMessages(id);
  renderThread();
  await markRead(id);
}

/* ------------------------------------------------------------------ thread */

/**
 * Redraws only the messages, leaving the header and composer where they are.
 *
 * The thread is polled every few seconds, and rebuilding all of it threw away
 * the composer on each pass — half-typed replies vanished after five seconds,
 * and the caret went with them. Nothing above or below the message list
 * changes between polls, so nothing above or below it is touched.
 */
/**
 * The scrolling middle of the thread: whatever is loaded, plus the way back to
 * what is not.
 */
/**
 * Whether a message belongs in the thread at all.
 *
 * `system` is WhatsApp talking to itself — pairing notices, protocol messages,
 * the housekeeping two copies of the app do. Stored, because the event log is
 * the record of what arrived, and not drawn, because it is not something
 * anybody said.
 */
const worthDrawing = (message) => message.kind !== "system";

function messagesNode(conversation) {
  const messages = el("div.thread__messages");
  if (state.canLoadOlder) messages.append(olderButton());
  for (const message of state.messages.filter(worthDrawing)) {
    messages.append(bubble(message, conversation));
  }
  if (!state.messages.length) {
    messages.append(el("div.empty", {}, ["No messages in this chat yet."]));
  }
  if (state.threadError) messages.append(el("div.alert", {}, [state.threadError]));
  // Both paint paths come through here, so this one line covers the poll, a
  // send, a retry and opening a chat.
  notifyThreadPainted();
  return messages;
}

/** Loads the previous page and leaves the reader looking at the same message. */
function olderButton() {
  const button = el("button.thread__older", { type: "button" }, ["Load earlier messages"]);

  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Loading…";

    const box = ui.thread.querySelector(".thread__messages");
    const heightBefore = box?.scrollHeight ?? 0;
    const topBefore = box?.scrollTop ?? 0;

    try {
      const added = await loadOlderMessages();
      paintMessages({ keepScroll: true });

      // Everything just added sits above what the reader was looking at, so
      // leaving scrollTop alone would jump them backwards by exactly that much.
      const grown = ui.thread.querySelector(".thread__messages");
      if (grown && added) grown.scrollTop = topBefore + (grown.scrollHeight - heightBefore);
    } catch (error) {
      button.disabled = false;
      button.textContent = "Load earlier messages";
      button.after(el("div.alert", {}, [error.message]));
    }
  });

  return button;
}

function paintMessages({ keepScroll = true } = {}) {
  const conversation = activeConversation();
  const previous = ui.thread.querySelector(".thread__messages");
  if (!conversation || !previous) return renderThread({ keepScroll });

  const wasAtBottom =
    previous.scrollTop + previous.clientHeight >= previous.scrollHeight - 60;
  const keptTop = previous.scrollTop;

  const messages = messagesNode(conversation);
  previous.replaceWith(messages);
  messages.scrollTop = !keepScroll || wasAtBottom ? messages.scrollHeight : keptTop;
}

function renderThread({ keepScroll = false } = {}) {
  const conversation = activeConversation();

  if (!conversation) {
    clear(ui.thread).append(
      el("div.empty.empty--thread", {}, [
        el("div.empty__art", {}, [icon("chat", { size: 30, stroke: 1.4 })]),
        el("div.empty__title", {}, ["No chat open"]),
        el("div.empty__note", {}, [
          "Pick a conversation on the left to read it and reply.",
        ]),
      ])
    );
    return;
  }

  const previous = ui.thread.querySelector(".thread__messages");
  // "At the bottom" means the newest message is on screen; a reader scrolled up
  // to something older should not be yanked back by a poll.
  const wasAtBottom =
    !previous || previous.scrollTop + previous.clientHeight >= previous.scrollHeight - 60;
  const keptTop = previous?.scrollTop ?? 0;

  const messages = messagesNode(conversation);
  const phone = sessionById(conversation.session_id);

  const title = conversationTitle(conversation);

  clear(ui.thread).append(
    el("header.thread__head", {}, [
      avatarFor(conversation, title, { small: true }),
      el("div.thread__who", {}, [
        el("div.thread__name", {}, [
          conversation.is_group ? el("span.chip--group", {}, ["Group"]) : null,
          title,
        ]),
        el("div.thread__sub", {}, [
          conversation.is_group
            ? "Several people write in this chat"
            : withPlus(conversationWaId(conversation)) || "No number on record",
          phone ? ` · on ${sessionName(phone)}` : "",
        ]),
      ]),
      // Search, starred and the contact panel, when the server has them.
      threadHeadExtras(),
    ]),
    messages,
    createComposer(conversation, {
      phone,
      onSent: async () => (await loadMessages(conversation.id), paintMessages()),
    })
  );

  // Newest at the bottom, so that is where the thread opens.
  if (!keepScroll || wasAtBottom) messages.scrollTop = messages.scrollHeight;
  else messages.scrollTop = keptTop;
}

/**
 * What a message with nothing in it actually was.
 *
 * A bubble that says "[unknown]" reads as a fault in this panel. Most of these
 * are not: WhatsApp carries polls, calls and withdrawn messages down the same
 * socket as text, and until now none of them had a name here.
 *
 * `unknown` is still possible and still says so — but plainly, because it means
 * "this panel does not draw that kind yet", not "something broke".
 */
const KIND_SAID = {
  deleted: "This message was deleted",
  poll: "Poll",
  call: "Call",
  order: "Order",
  product: "Product",
  interactive: "Button reply",
  invite: "Group invitation",
  contacts: "Contact card",
  location: "Location",
  sticker: "Sticker",
  pending: "Waiting for this message",
  system: "",
  text: "",
  unknown: "Message not shown here",
};

function kindSentence(kind) {
  const key = String(kind || "").toLowerCase();
  if (key in KIND_SAID) return KIND_SAID[key] || "Message not shown here";
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** The words of the message this one answers, "" if unknown, null if none. */
function quotedFor(message) {
  if (message.reply_to) return message.reply_to.body || `[${message.reply_to.kind || "message"}]`;
  if (!message.reply_to_id) return null;

  const target = state.messages.find((m) => String(m.id) === String(message.reply_to_id));
  if (!target) return "Replying to an earlier message";
  return target.body || `[${target.kind || "message"}]`;
}

/**
 * The picture, the voice note or the file — shown as what it is.
 *
 * Two URLs, because the server offers two answers for the same bytes. The
 * download flattens everything to application/octet-stream with nosniff, which
 * is right for a document a stranger sent and fatal for a photograph: nosniff
 * is exactly the instruction not to work out that those bytes are a JPEG, so an
 * <img> pointing there rendered nothing at all. Every picture in this panel was
 * a broken image icon. The inline route declares the real type, for the handful
 * of formats a browser decodes rather than executes.
 */
function attachment(message) {
  // The URLs arrive as "/api/media/5" — already absolute, so they have to be
  // re-based like everything else or they leave the /qr/ prefix behind.
  const download = onApi(message.media_url || `api/media/${message.media_id}`);
  const inline = onApi(message.media_inline_url || `api/media/${message.media_id}/inline`);

  const mime = String(message.media_mime || message.mime_type || "").toLowerCase();
  const kind = message.kind || "";

  // The file never arrived. Said in words rather than drawn as a broken image
  // or a player with nothing behind it: the message itself is still worth
  // reading, and what is missing is worth naming.
  if (message.media_downloaded === false) {
    return el("div.msg__missing", {}, [
      icon("file", { size: 15 }),
      el("span", {}, [`This ${kind || "attachment"} could not be downloaded from the phone.`]),
    ]);
  }

  // The mime type when the server knows it, the kind when it does not — an
  // imported message whose file never downloaded has a kind and nothing else.
  const looks = (prefix, ...kinds) => mime.startsWith(prefix) || kinds.includes(kind);

  if (looks("image/", "image", "sticker")) {
    return el("img.msg__thumb", {
      src: inline,
      alt: message.media_name || "",
      loading: "lazy",
      onclick: () => window.open(inline, "_blank", "noopener"),
    });
  }

  if (looks("audio/", "audio")) {
    // A voice note is listened to in place. Downloading a file to hear what a
    // customer said, and then finding it again to hear it twice, is not a
    // reasonable thing to ask of somebody answering forty chats.
    //
    // Drawn by thread-extras rather than by <audio controls>, which renders the
    // platform's own white widget in the middle of a dark thread.
    return voiceNote(message, inline);
  }

  if (looks("video/", "video")) {
    return el("video.msg__video", { src: inline, controls: true, preload: "metadata" });
  }

  return el("a.msg__file", { href: download, target: "_blank", rel: "noopener" }, [
    icon("file", { size: 17 }),
    el("span.msg__file-name", {}, [message.media_name || message.file_name || message.kind || "File"]),
    el("span.msg__file-size", {}, [formatBytes(message.media_size ?? message.size_bytes)]),
  ]);
}

/**
 * A failure, said once and briefly, with the way out next to it.
 *
 * The library's errors are stack traces with a bundle URL in them. Printed
 * whole inside the bubble they buried the message the agent was trying to
 * send; the full text stays available on hover, and the button is the part
 * that is actually useful.
 */
function failure(message, conversation) {
  const detail = String(message.error_detail || "The message was not sent.");
  const short = detail.split(/\s*\(https?:\/\//)[0].split("\n")[0].trim() || "The message was not sent.";

  const retry = el("button.msg__retry", { type: "button", title: "Send this message again" }, ["Retry"]);
  retry.addEventListener("click", async () => {
    retry.disabled = true;
    retry.textContent = "Sending…";
    try {
      await api("api/send", {
        method: "POST",
        body: {
          session_id: conversation.session_id,
          to: conversationWaId(conversation),
          kind: "text",
          body: message.body,
        },
      });
      await loadMessages(conversation.id);
      // Messages only, so the cursor stays in the box the agent is still using.
      paintMessages();
    } catch (error) {
      retry.disabled = false;
      retry.textContent = "Retry";
      retry.after(el("span.msg__error-note", {}, [error.message]));
    }
  });

  return el("div.msg__failure", { title: detail }, [
    el("span.msg__error", {}, [short]),
    // Only text can be sent again from here: a media retry would need the file
    // the server was given, and the panel was never told what it was.
    message.body && message.kind === "text" ? retry : null,
  ]);
}

function bubble(message, conversation) {
  const outbound = message.direction === "out";
  const node = el("div.msg", {
    // Named so composer.js can quote it. Nothing else reads this.
    "data-id": String(message.id),
    class: [outbound ? "msg--out" : "", message.status === "failed" ? "msg--failed" : ""]
      .filter(Boolean)
      .join(" "),
  });

  // In a group there is no single customer behind the chat, so an inbound
  // message that does not say who wrote it is unattributable.
  if (conversation.is_group && !outbound && message.author_wa_id) {
    node.append(el("div.msg__author", {}, [withPlus(message.author_wa_id)]));
  }

  const quoted = quotedFor(message);
  if (quoted !== null) {
    node.append(el("div.msg__quote", {}, [icon("reply", { size: 12 }), quoted]));
  }

  if (message.media_url || message.media_id) node.append(attachment(message));

  if (message.body) node.append(el("div.msg__body", {}, [message.body]));
  else if (!message.media_url && !message.media_id) {
    // In words, not in brackets. "[unknown]" told an agent that something had
    // gone wrong, when almost always nothing had — it was a poll, a missed
    // call, or a message the other person deleted.
    node.append(el("div.msg__body.msg__body--said", {}, [kindSentence(message.kind)]));
  }

  if (message.status === "failed") node.append(failure(message, conversation));

  node.append(
    el("div.msg__meta", {}, [
      stamp(message.created_at),
      outbound ? deliveryTick(message.status) : null,
    ])
  );

  const reactions = Object.values(message.reactions || {}).filter(Boolean);
  if (reactions.length) {
    node.append(
      el("div.msg__reactions", {}, reactions.map((emoji) => el("span.reaction", {}, [emoji])))
    );
  }

  // The id to be found by, the emoji bar, the star and the ⋯ menu.
  return decorateBubble(node, message);
}

/**
 * What a phone shows beside a message it sent: one tick queued or sent, two
 * delivered, two blue read.
 *
 * The word was printed here before ("· delivered"), which is both longer than
 * the message half the time and a vocabulary the agent has to learn. The ticks
 * are the ones they already know from WhatsApp itself; the word stays on the
 * title, for anyone who wants it.
 */
function deliveryTick(status) {
  const TICKS = {
    queued: { name: "clock", label: "Queued" },
    sent: { name: "check", label: "Sent" },
    delivered: { name: "checkDouble", label: "Delivered" },
    read: { name: "checkDouble", label: "Read", modifier: "msg__tick--read" },
    failed: { name: "alert", label: "Not sent", modifier: "msg__tick--failed" },
  };

  const tick = TICKS[status];
  if (!tick) return null;

  return el(
    "span.msg__tick",
    { class: tick.modifier || "", title: tick.label },
    [icon(tick.name, { size: 13, stroke: 2 })]
  );
}

/* ------------------------------------------------------------ phones dialog */

function openPhones() {
  const listNode = el("div.cards");
  const d = dialog({
    title: "Linked phones",
    wide: true,
    body: el("div.dlg__body", {}, [
      el("div.dlg__row", {}, [
        el("p.dlg__text", {}, [
          "Phones connected by scanning a QR code, separate from the Business Platform numbers. ",
          "Everything on a phone when it is linked is imported and kept here, and stays here " +
            "whether or not the phone remains connected.",
        ]),
        // Linking and unlinking are an administrator's decisions, and the server
        // says so with a 403. Drawing the buttons for an agent would only offer
        // them a refusal.
        state.me.is_admin
          ? el("div.dlg__row", {}, [
              el("button.btn.btn--ghost", {
                type: "button",
                onclick: () => {
                  d.close();
                  openPhonesAdmin({ dialog, askConfirm, onChanged: () => refresh({ keepScroll: false }) });
                },
              }, ["Agents and reports"]),
              el("button.btn", { type: "button", onclick: () => linkPhone(d) }, ["Link a phone"]),
            ])
          : null,
      ]),
      listNode,
    ]),
  });

  const paint = () => {
    clear(listNode);
    if (!state.sessions.length) {
      listNode.append(el("div.empty", {}, ["No phone is linked yet."]));
      return;
    }
    for (const session of state.sessions) {
      const look = statusOf(session.status);
      listNode.append(
        el("div.card", {}, [
          el("div.card__top", {}, [
            el("div", {}, [
              el("div.card__label", {}, [sessionName(session)]),
              session.label && session.phone_number
                ? el("div.card__phone", {}, [withPlus(session.phone_number)])
                : null,
            ]),
            el("span.chip", { class: look.chip }, [look.text]),
            // How close this number is to being banned, beside whether it is
            // connected. The two are not the same question and a card that
            // answers only the first is the one an agent reads.
            riskChipFor(session.id),
          ]),
          el("div.card__seen", {}, [
            session.last_seen_at ? `Last seen ${fullStamp(session.last_seen_at)}` : "Never connected",
          ]),
          // A spinner beside the words while it runs, and a bar under them —
          // "12 of 84" alone is a number somebody has to watch for a while
          // before they can tell whether anything is moving.
          isImporting(session)
            ? el("div.card__history.card__history--busy", {}, [
                el("div.card__history-line", {}, [
                  el("span.imp__spinner.imp__spinner--sm"),
                  el("span", {}, [historyNote(session)]),
                ]),
                // No inline width while the total is still unknown: an inline
                // style outranks the stylesheet, so `width:0%` would silently
                // flatten the sweeping bar that says "counting" back to an
                // empty one that says "nothing is happening".
                el(
                  "div.imp__bar",
                  { class: historyFraction(session.history) === null ? "imp__bar--waiting" : "" },
                  [
                    el("div.imp__fill", {
                      style:
                        historyFraction(session.history) === null
                          ? null
                          : `width:${Math.round(historyFraction(session.history) * 100)}%`,
                    }),
                  ]
                ),
              ])
            : el("div.card__history", {}, [
                historyNote(session) ||
                  `History imported${
                    session.history?.messages
                      ? ` — ${session.history.messages.toLocaleString()} messages`
                      : ""
                  }`,
              ]),
          // Shown in full, never truncated: this is the sentence that explains
          // why a number stopped working, and it is the only one there is.
          session.last_error ? el("div.card__why", {}, [session.last_error]) : null,
          el("div.card__actions", {}, [
            session.status === "ready" || !state.me.is_admin
              ? null
              : el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: () => openQr(session.id) }, [
                  "Show QR",
                ]),
            state.me.is_admin
              ? el(
                  "button.btn.btn--danger.btn--sm",
                  { type: "button", onclick: () => disconnect(session, paint) },
                  ["Disconnect"]
                )
              : null,
          ]),
        ])
      );
    }
  };

  loadSessions().then(paint);
  paint();

  // Redrawn while it is open, so an import in progress counts up in front of
  // whoever is watching it. It stops itself once the dialog is gone rather than
  // being unsubscribed — the dialog can be closed by the X, the backdrop,
  // Escape, or by "Link a phone" replacing it, and only one of those is an
  // event anything here could listen for.
  const repaint = setInterval(() => {
    if (!listNode.isConnected) return clearInterval(repaint);
    if (state.sessions.some(isImporting)) paint();
  }, 3000);
}

async function linkPhone(phonesDialog) {
  const label = await askText({
    title: "Link a phone",
    label: "Name this phone (optional)",
    placeholder: "Marketing SIM",
    confirmLabel: "Continue",
  });
  if (label === null) return;

  try {
    const created = await api("api/sessions", { method: "POST", body: { label: label.trim() } });
    phonesDialog?.close();
    openQr(created?.id ?? created?.session?.id);
  } catch (error) {
    await askConfirm({
      title: "The phone could not be linked",
      message: error.message,
      confirmLabel: "Close",
    });
  }
}

async function disconnect(session, done) {
  // Worded as unlinking because that is now all it is. Nothing this button does
  // reaches the conversations: the row stays, the chats stay, and scanning the
  // same row again picks the phone back up where it left off.
  const sure = await askConfirm({
    title: "Disconnect this phone",
    message:
      `${sessionName(session)} will be logged out and has to be scanned again to reconnect. ` +
      "Every chat, message and file already imported is kept, and reconnecting reads only " +
      "what arrived while it was away.",
    confirmLabel: "Disconnect",
    danger: true,
  });
  if (!sure) return;

  try {
    await api(`api/sessions/${session.id}/disconnect`, { method: "POST" });
    await loadSessions();
    renderPhoneSelect();
    done?.();
    await refresh({ keepScroll: false });
  } catch (error) {
    await askConfirm({ title: "Could not disconnect", message: error.message, confirmLabel: "Close" });
  }
}

/* ------------------------------------------------------------ import panel */

/**
 * What the dialog turns into the moment a phone is linked.
 *
 * Scanning the code is not the end of setting a phone up — the months of
 * conversation already on it still have to be read across, and that takes
 * minutes. Without this the dialog said "Connected" and closed onto a chat list
 * that filled in slowly for no visible reason, which reads as a broken import
 * rather than one still running.
 *
 * It says what is happening, how far along it is and how much longer it will
 * take, and it says plainly that the window can be closed — the import is on
 * the server and does not need anybody watching it.
 */
function importPanel(sessionId, close) {
  const spinner = el("span.imp__spinner");
  const headline = el("div.imp__headline", {}, ["Reading your WhatsApp — please wait"]);
  const fill = el("div.imp__fill");
  const bar = el("div.imp__bar", {}, [fill]);
  const detail = el("div.imp__detail", {}, ["Getting ready…"]);
  const eta = el("div.imp__eta");
  const closeButton = el("button.btn.btn--ghost", { type: "button", onclick: close }, [
    "Close and keep working",
  ]);

  const panel = el("div.imp", {}, [
    el("div.imp__top", {}, [spinner, headline]),
    bar,
    detail,
    eta,
    el("p.imp__note", {}, [
      "Your chats are being copied from the phone into this inbox, six months back. " +
        "They appear in the list on the left as they arrive, and stay here whether or " +
        "not the phone remains connected.",
    ]),
    el("div.dlg__actions", {}, [closeButton]),
  ]);

  let timer = null;
  const stop = () => timer && clearInterval(timer);
  panel.stop = stop;

  async function tick() {
    await loadSessions();
    renderPhoneSelect();

    const session = sessionById(sessionId);
    const history = session?.history || {};
    const fraction = historyFraction(history);

    if (history.status === "done") {
      stop();
      spinner.classList.add("imp__spinner--done");
      headline.textContent = "Your WhatsApp is ready";
      fill.style.width = "100%";
      detail.textContent = history.messages
        ? `${history.messages.toLocaleString()} messages imported from ${history.chatsTotal} chats.`
        : "Everything on this phone was already here.";
      eta.textContent = "";
      clear(closeButton).append("Open the inbox");
      refresh({ keepScroll: false });
      return;
    }

    if (history.status === "failed") {
      stop();
      spinner.classList.add("imp__spinner--failed");
      headline.textContent = "The import stopped early";
      detail.textContent = history.error || "The reason was not recorded.";
      eta.textContent = "It will pick up again the next time this phone connects.";
      return;
    }

    // The bar is indeterminate until the chat list has been counted, because a
    // width of zero for the first half-minute looks like nothing is happening.
    bar.classList.toggle("imp__bar--waiting", fraction === null);
    fill.style.width = fraction === null ? "" : `${Math.round(fraction * 100)}%`;

    detail.textContent = !history.chatsTotal
      ? "Reading the list of chats on this phone…"
      : `Chat ${history.chatsDone} of ${history.chatsTotal}` +
        (history.messages ? ` · ${history.messages.toLocaleString()} messages so far` : "");

    const left = session ? etaFor(session) : "";
    eta.textContent = left ? `${left} left` : "Working out how long this will take…";
  }

  tick();
  timer = setInterval(tick, 3000);
  return panel;
}

/* ---------------------------------------------------------------- QR dialog */

async function openQr(id) {
  if (!id) return;

  // A phone that was disconnected on purpose has no client behind it and no
  // reconnect timer either — cancelling that timer is what makes a deliberate
  // disconnect stick. So nothing would ever produce a code, and this dialog
  // would wait for one for ever. Asking for the client back first is what turns
  // "Show QR" into something that happens.
  await api(`api/sessions/${id}/relink`, { method: "POST" }).catch(() => {});

  const frame = el("div.qr__frame", {}, [el("div.qr__pending", {}, ["Waiting for a code…"])]);
  const status = el("div.qr__status", {}, ["Starting up…"]);
  const problem = el("div.alert", { hidden: true });

  const body = el("div.qr", {}, [
    // Before the code, not after it. Somebody about to scan is the last
    // person who can decide not to, and a ban cannot be undone.
    el("div.qr__warning", {}, [
      el("b", {}, ["Only link a number kept for this purpose."]),
      "Numbers on the WhatsApp Business Platform must not be linked here — a ban is permanent.",
    ]),
    frame,
    status,
    problem,
    el("ol.qr__steps", {}, [
      el("li", {}, ["Open WhatsApp on the phone."]),
      el("li", {}, ["Go to Settings, then Linked devices."]),
      el("li", {}, ["Tap Link a device and scan the code above."]),
    ]),
  ]);

  const d = dialog({ title: "Link a phone", body });

  let shown = "";
  let timer = null;
  let panel = null;
  const stop = () => {
    if (timer) clearInterval(timer);
    panel?.stop?.();
  };
  d.node.addEventListener("dismiss", stop);

  async function poll() {
    let data;
    try {
      data = await api(`api/sessions/${id}/qr`);
      problem.hidden = true;
    } catch (error) {
      problem.hidden = false;
      clear(problem).append(error.message);
      return;
    }

    status.textContent = statusOf(data.status).text;

    if (data.status === "ready") {
      stop();
      // The number is not on this route — it only answers {status,
      // qr_data_url} — so the sessions have to be refetched before it can be
      // named, and the panel behind the dialog wants the update anyway.
      await loadSessions();
      renderPhoneSelect();
      const session = sessionById(id);

      // Scanning the code is not the end of it. The dialog stays open and turns
      // into the import, because the months of conversation on this phone are
      // still being read across and a chat list filling in slowly with no
      // explanation reads as something broken.
      panel = importPanel(id, () => {
        stop();
        d.close();
      });
      clear(body).append(
        el("div.qr__connected", {}, [
          withPlus(session?.phone_number)
            ? `Connected as ${withPlus(session.phone_number)}`
            : "Connected",
        ]),
        panel
      );
      refresh({ keepScroll: false });
      return;
    }

    if (data.status === "banned" || data.status === "disconnected") {
      stop();
      clear(frame).append(
        el("div.qr__pending", {}, [
          data.status === "banned" ? "This number has been banned." : "This phone disconnected.",
        ])
      );
      problem.hidden = false;
      clear(problem).append(
        sessionById(id)?.last_error ||
          "WhatsApp ended the link. A banned number cannot be recovered."
      );
      loadSessions().then(renderPhoneSelect);
      return;
    }

    if (data.qr_data_url && data.qr_data_url !== shown) {
      shown = data.qr_data_url;
      clear(frame).append(el("img.qr__img", { src: data.qr_data_url, alt: "QR code to link a phone" }));
    }
  }

  poll();
  timer = setInterval(poll, POLL_QR_MS);
}

/* -------------------------------------------------------------------- boot */

async function boot() {
  applyTheme();
  await Promise.all([loadMe(), loadSessions(), loadConversations()]);

  // Before the first render, so the header knows which of its buttons the
  // server can answer for. Not awaited: it ends in two probe requests, and a
  // panel that waits on those to draw anything is a panel that looks broken
  // whenever they are slow.
  installThreadExtras({
    el, clear, api, onApi, asList, stamp, withPlus, formatBytes, icon, dialog,
    state, ui, activeConversation, conversationTitle, conversationWaId,
    sessionById, sessionName, avatarFor,
    loadMessages, loadOlderMessages, paintMessages, selectConversation,
  }).then(renderThread);

  // Fills the New chat button and the filter strip, both of which are already
  // in the shell as empty containers, and loads the risk figures behind them.
  installNewChat({
    el, clear, api, asList, icon, dialog, withPlus, state,
    sessionName, paintConversations, refresh, selectConversation,
  }).then(paintConversations);

  clear(root).append(layout);

  // Above everything, because it is a warning about what somebody is in the
  // middle of doing rather than a thing to go and look at.
  installSafetyBanner({
    el, clear, api, asList, withPlus,
    mount: (bar) => root.prepend(bar),
  });

  renderPhoneSelect();
  paintConversations();
  renderThread();

  poller = setInterval(() => refresh(), POLL_CHAT_MS);

  // Coming back to the tab is the moment the open chat is genuinely being read;
  // everything that arrived while it was hidden was deliberately left counted.
  document.addEventListener("visibilitychange", () => markRead(state.conversationId));
}

boot().catch((error) => {
  clear(root).append(el("div.boot-error", {}, [el("div.alert", {}, [`The panel could not start: ${error.message}`])]));
  console.error("[wa-qr] boot failed:", error);
});
