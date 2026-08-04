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

const POLL_CHAT_MS = 5000;   // no socket on this service; the list is polled
const POLL_QR_MS = 3000;     // the code itself rotates roughly every 20 seconds
const MAX_BODY = 4096;

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
      el("button.dlg__x", { type: "button", title: "Close" }, ["×"]),
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
  sessions: [],
  phoneFilter: "",        // "" is every phone
  conversations: [],
  conversationId: null,
  messages: [],
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
  thread: el("section.thread"),
};

const layout = el("div.app", {}, [
  el("aside.side", {}, [
    el("div.side__top", {}, [
      el("div.side__title", {}, ["Linked phones"]),
      el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: openPhones }, ["Manage"]),
    ]),
    el("div.side__filters", {}, [ui.phoneSelect, ui.search]),
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

async function loadMessages(id) {
  try {
    const payload = await api(`api/conversations/${id}/messages`);
    // Oldest first, which is reading order. Sorted here for the same reason the
    // conversations are: the route does not promise an order, and a thread that
    // renders backwards is worse than one that loads a moment later.
    state.messages = asList(payload, "messages").sort(
      (a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0)
    );
    state.threadError = "";
  } catch (error) {
    state.threadError = error.message;
    state.messages = [];
  }
}

async function refresh({ keepScroll = true } = {}) {
  await Promise.all([loadSessions(), loadConversations()]);
  renderPhoneSelect();
  paintConversations();
  if (state.conversationId) {
    await loadMessages(state.conversationId);
    // Only the messages: a poll must not take the composer with it.
    paintMessages({ keepScroll });
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
  if (!state.search) return state.conversations;
  return state.conversations.filter((c) =>
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
    ui.convs.append(
      el(
        "button.conv",
        {
          type: "button",
          class: String(conversation.id) === String(state.conversationId) ? "is-active" : "",
          onclick: () => selectConversation(conversation.id),
        },
        [
          el("div.conv__line", {}, [
            el("span.conv__name", {}, [
              conversation.is_group ? el("span.chip--group", {}, ["Group"]) : null,
              el("span", {}, [conversationTitle(conversation)]),
            ]),
            el("span.conv__when", {}, [stamp(conversation.last_message_at)]),
          ]),
          el("div.conv__line", {}, [
            el("span.conv__last", {}, [
              conversation.last_message_preview ||
                (conversation.last_message_kind ? `[${conversation.last_message_kind}]` : ""),
            ]),
            conversation.unread_count
              ? el("span.conv__unread", {}, [String(conversation.unread_count)])
              : null,
          ]),
          // Only worth naming while more than one phone is in the list.
          !state.phoneFilter && phone
            ? el("div.conv__phone", {}, [sessionName(phone)])
            : null,
        ]
      )
    );
  }
}

async function selectConversation(id) {
  state.conversationId = id;
  state.messages = [];
  renderThread();
  paintConversations();
  await loadMessages(id);
  renderThread();
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
function paintMessages({ keepScroll = true } = {}) {
  const conversation = activeConversation();
  const previous = ui.thread.querySelector(".thread__messages");
  if (!conversation || !previous) return renderThread({ keepScroll });

  const wasAtBottom =
    previous.scrollTop + previous.clientHeight >= previous.scrollHeight - 60;
  const keptTop = previous.scrollTop;

  const messages = el("div.thread__messages");
  for (const message of state.messages) messages.append(bubble(message, conversation));
  if (!state.messages.length) {
    messages.append(el("div.empty", {}, ["No messages in this chat yet."]));
  }
  if (state.threadError) messages.append(el("div.alert", {}, [state.threadError]));

  previous.replaceWith(messages);
  messages.scrollTop = !keepScroll || wasAtBottom ? messages.scrollHeight : keptTop;
}

function renderThread({ keepScroll = false } = {}) {
  const conversation = activeConversation();

  if (!conversation) {
    clear(ui.thread).append(el("div.empty.empty--thread", {}, ["Select a chat on the left."]));
    return;
  }

  const previous = ui.thread.querySelector(".thread__messages");
  // "At the bottom" means the newest message is on screen; a reader scrolled up
  // to something older should not be yanked back by a poll.
  const wasAtBottom =
    !previous || previous.scrollTop + previous.clientHeight >= previous.scrollHeight - 60;
  const keptTop = previous?.scrollTop ?? 0;

  const messages = el("div.thread__messages");
  for (const message of state.messages) messages.append(bubble(message, conversation));
  if (!state.messages.length) {
    messages.append(el("div.empty", {}, ["No messages in this chat yet."]));
  }
  if (state.threadError) messages.append(el("div.alert", {}, [state.threadError]));

  const phone = sessionById(conversation.session_id);

  clear(ui.thread).append(
    el("header.thread__head", {}, [
      el("div.thread__who", {}, [
        el("div.thread__name", {}, [
          conversation.is_group ? el("span.chip--group", {}, ["Group"]) : null,
          conversationTitle(conversation),
        ]),
        el("div.thread__sub", {}, [
          conversation.is_group
            ? "Several people write in this chat"
            : withPlus(conversationWaId(conversation)) || "No number on record",
          phone ? ` · on ${sessionName(phone)}` : "",
        ]),
      ]),
    ]),
    messages,
    composer(conversation)
  );

  // Newest at the bottom, so that is where the thread opens.
  if (!keepScroll || wasAtBottom) messages.scrollTop = messages.scrollHeight;
  else messages.scrollTop = keptTop;
}

/** The words of the message this one answers, "" if unknown, null if none. */
function quotedFor(message) {
  if (message.reply_to) return message.reply_to.body || `[${message.reply_to.kind || "message"}]`;
  if (!message.reply_to_id) return null;

  const target = state.messages.find((m) => String(m.id) === String(message.reply_to_id));
  if (!target) return "Replying to an earlier message";
  return target.body || `[${target.kind || "message"}]`;
}

function attachment(message) {
  // media_url arrives as "/api/media/5" — already absolute, so it has to be
  // re-based like everything else or it leaves the /qr/ prefix behind.
  const url = onApi(message.media_url || `api/media/${message.media_id}`);
  const mime = message.media_mime || message.mime_type || "";
  const isImage = mime.startsWith("image/") || ["image", "sticker"].includes(message.kind);

  if (isImage) {
    return el("img.msg__thumb", {
      src: url,
      alt: message.media_name || "",
      loading: "lazy",
      onclick: () => window.open(url, "_blank", "noopener"),
    });
  }

  return el("a.msg__file", { href: url, target: "_blank", rel: "noopener" }, [
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
  if (quoted !== null) node.append(el("div.msg__quote", {}, [quoted]));

  if (message.media_url || message.media_id) node.append(attachment(message));

  if (message.body) node.append(el("div.msg__body", {}, [message.body]));
  else if (!message.media_url && !message.media_id) {
    node.append(el("div.msg__body", {}, [`[${message.kind || "message"}]`]));
  }

  if (message.status === "failed") node.append(failure(message, conversation));

  node.append(
    el("div.msg__meta", {}, [
      stamp(message.created_at),
      outbound && message.status ? ` · ${message.status}` : "",
    ])
  );

  const reactions = Object.values(message.reactions || {}).filter(Boolean);
  if (reactions.length) {
    node.append(
      el("div.msg__reactions", {}, reactions.map((emoji) => el("span.reaction", {}, [emoji])))
    );
  }

  return node;
}

function composer(conversation) {
  const phone = sessionById(conversation.session_id);
  if (phone && phone.status !== "ready") {
    return el("div.composer.composer--locked", {}, [
      `${sessionName(phone)} is ${statusOf(phone.status).text.toLowerCase()} — messages cannot be sent until it is ready.`,
    ]);
  }

  const input = el("textarea.composer__input", {
    rows: 1,
    placeholder: "Write a message…",
    maxlength: String(MAX_BODY),
  });
  const send = el("button.btn", { type: "button" }, ["Send"]);
  const problem = el("div.composer__error", { hidden: true });

  async function submit() {
    const body = input.value.trim();
    if (!body) return;

    send.disabled = true;
    send.textContent = "Sending…";
    problem.hidden = true;
    try {
      await api("api/send", {
        method: "POST",
        body: {
          session_id: conversation.session_id,
          to: conversationWaId(conversation),
          kind: "text",
          body,
        },
      });
      input.value = "";
      // Refetched rather than guessed: the row the server wrote carries the id
      // and status a locally invented bubble would not have.
      await loadMessages(conversation.id);
      // Messages only, so the cursor stays in the box the agent is still using.
      paintMessages();
    } catch (error) {
      send.disabled = false;
      send.textContent = "Send";
      problem.hidden = false;
      clear(problem).append(error.message);
    }
  }

  send.addEventListener("click", submit);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });

  const bar = el("div.composer", {}, [input, send]);
  queueMicrotask(() => input.focus());
  return el("footer.thread__foot", {}, [problem, bar]);
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
          "Phones connected by scanning a QR code, separate from the Business Platform numbers.",
        ]),
        el("button.btn", { type: "button", onclick: () => linkPhone(d) }, ["Link a phone"]),
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
          ]),
          el("div.card__seen", {}, [
            session.last_seen_at ? `Last seen ${fullStamp(session.last_seen_at)}` : "Never connected",
          ]),
          // Shown in full, never truncated: this is the sentence that explains
          // why a number stopped working, and it is the only one there is.
          session.last_error ? el("div.card__why", {}, [session.last_error]) : null,
          el("div.card__actions", {}, [
            session.status === "ready"
              ? null
              : el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: () => openQr(session.id) }, [
                  "Show QR",
                ]),
            el("button.btn.btn--danger.btn--sm", { type: "button", onclick: () => disconnect(session, paint) }, [
              "Disconnect",
            ]),
          ]),
        ])
      );
    }
  };

  loadSessions().then(paint);
  paint();
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
  // Worded as removal because that is what the server does: DELETE logs the
  // phone out, wipes its auth data and drops the row.
  const sure = await askConfirm({
    title: "Disconnect this phone",
    message: `${sessionName(session)} will be logged out and has to be linked again from scratch. Its chat history is kept.`,
    confirmLabel: "Disconnect",
    danger: true,
  });
  if (!sure) return;

  try {
    await api(`api/sessions/${session.id}`, { method: "DELETE" });
    await loadSessions();
    renderPhoneSelect();
    done?.();
    await refresh({ keepScroll: false });
  } catch (error) {
    await askConfirm({ title: "Could not disconnect", message: error.message, confirmLabel: "Close" });
  }
}

/* ---------------------------------------------------------------- QR dialog */

function openQr(id) {
  if (!id) return;

  const frame = el("div.qr__frame", {}, [el("div.qr__pending", {}, ["Waiting for a code…"])]);
  const status = el("div.qr__status", {}, ["Starting up…"]);
  const problem = el("div.alert", { hidden: true });

  const d = dialog({
    title: "Link a phone",
    body: el("div.qr", {}, [
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
    ]),
  });

  let shown = "";
  let timer = null;
  const stop = () => timer && clearInterval(timer);
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
      clear(frame).append(
        el("div.qr__connected", {}, [
          withPlus(session?.phone_number) ? `Connected as ${withPlus(session.phone_number)}` : "Connected",
        ])
      );
      status.textContent = "";
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
  await Promise.all([loadSessions(), loadConversations()]);

  clear(root).append(layout);
  renderPhoneSelect();
  paintConversations();
  renderThread();

  poller = setInterval(() => refresh(), POLL_CHAT_MS);
}

boot().catch((error) => {
  clear(root).append(el("div.boot-error", {}, [el("div.alert", {}, [`The panel could not start: ${error.message}`])]));
  console.error("[wa-qr] boot failed:", error);
});
