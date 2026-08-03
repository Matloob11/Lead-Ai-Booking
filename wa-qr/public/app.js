/**
 * The panel for the QR-linked channel: which phones are linked, the QR for
 * linking another, and the chats coming off them.
 *
 * Plain ES modules, no framework, no build — the main panel is built the same
 * way and this one is deployed the same way, by copying the folder.
 *
 * Nothing a customer wrote is ever put through innerHTML. Every message body,
 * contact name and group subject on this screen was typed by somebody outside
 * the company, so it is only ever a text node.
 */

const POLL_QR_MS = 3000;      // the QR itself rotates roughly every 20 seconds
const POLL_CHAT_MS = 5000;    // no socket on this service; the list is polled
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

async function api(path, { method = "GET", body } = {}) {
  const init = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const response = await fetch(path, init);
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
const nav = document.getElementById("nav");

const state = {
  view: "sessions", // sessions | qr | chats
  sessions: [],
  sessionId: null,
  conversations: [],
  conversationId: null,
  messages: [],
  error: "",
};

/** Every running interval, so switching views cannot leave one behind. */
let timers = [];
const every = (ms, fn) => timers.push(setInterval(fn, ms));
function stopTimers() {
  timers.forEach(clearInterval);
  timers = [];
}

function go(view, patch = {}) {
  stopTimers();
  Object.assign(state, patch, { view, error: "" });
  render();
}

const sessionById = (id) => state.sessions.find((s) => String(s.id) === String(id)) || null;

/* -------------------------------------------------------------------- nav */

function renderNav() {
  clear(nav).append(
    el("button.tab", {
      type: "button",
      class: state.view === "sessions" ? "is-active" : "",
      onclick: () => go("sessions"),
    }, ["Phones"]),
    el("button.tab", {
      type: "button",
      class: state.view === "chats" ? "is-active" : "",
      // Chats belong to a linked phone; without one there is nothing to show.
      disabled: !state.sessionId,
      title: state.sessionId ? "" : "Link a phone first",
      onclick: () => openChats(state.sessionId),
    }, ["Chats"])
  );
}

function render() {
  renderNav();
  if (state.view === "sessions") return renderSessions();
  if (state.view === "qr") return renderQr();
  if (state.view === "chats") return renderChats();
}

function fail(message) {
  state.error = message;
  render();
}

/* ------------------------------------------------------- screen 1: phones */

async function loadSessions() {
  try {
    state.sessions = asList(await api("/api/sessions"), "sessions");
    state.error = "";
  } catch (error) {
    state.error = error.message;
  }
}

function renderSessions() {
  const page = el("div.page");
  const list = el("div.cards");

  page.append(
    el("div.page__head", {}, [
      el("div", {}, [
        el("h1.page__title", {}, ["Linked phones"]),
        el("p.page__hint", {}, ["Phones connected by scanning a QR code, separate from the Business Platform numbers."]),
      ]),
      el("button.btn", { type: "button", onclick: linkPhone }, ["Link a phone"]),
    ]),
    state.error ? el("div.alert", {}, [state.error]) : null,
    list
  );

  clear(root).append(page);
  paint();

  // Statuses move on their own — a scan completing, a phone dropping off — so
  // the list refreshes rather than waiting to be reloaded.
  every(POLL_CHAT_MS, () => loadSessions().then(paint));
  loadSessions().then(paint);

  function paint() {
    clear(list);

    if (!state.sessions.length) {
      list.append(el("div.empty", {}, ["No phone is linked yet. Use “Link a phone” to connect one."]));
      return;
    }

    for (const session of state.sessions) {
      const look = statusOf(session.status);
      const banned = session.status === "banned";

      list.append(
        el("div.card", {}, [
          el("div.card__top", {}, [
            el("div", {}, [
              el("div.card__label", {}, [session.label || withPlus(session.phone_number) || "Unnamed phone"]),
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
              ? el("button.btn.btn--ghost", { type: "button", onclick: () => openChats(session.id) }, ["Open chats"])
              : el("button.btn.btn--ghost", { type: "button", onclick: () => openQr(session.id) }, [
                  banned ? "Details" : "Show QR",
                ]),
            el("button.btn.btn--danger", { type: "button", onclick: () => disconnect(session) }, ["Disconnect"]),
          ]),
        ])
      );
    }
  }
}

async function linkPhone() {
  const label = window.prompt("Name this phone (optional) — for example “Marketing SIM”.", "");
  if (label === null) return; // cancelled

  try {
    const created = await api("/api/sessions", { method: "POST", body: { label: label.trim() } });
    openQr(created?.id ?? created?.session?.id);
  } catch (error) {
    fail(error.message);
  }
}

async function disconnect(session) {
  const name = session.label || withPlus(session.phone_number) || `phone #${session.id}`;
  if (!window.confirm(`Disconnect ${name}? It will stop receiving messages until it is linked again.`)) {
    return;
  }
  try {
    await api(`/api/sessions/${session.id}/disconnect`, { method: "POST" });
    if (String(state.sessionId) === String(session.id)) state.sessionId = null;
    await loadSessions();
    go("sessions");
  } catch (error) {
    fail(error.message);
  }
}

/* ----------------------------------------------------------- screen 2: QR */

function openQr(id) {
  if (!id) return fail("The phone was created but came back without an id.");
  go("qr", { sessionId: id });
}

function renderQr() {
  const frame = el("div.qr__frame", {}, [el("div.qr__pending", {}, ["Waiting for a code…"])]);
  const status = el("div.qr__status", {}, ["Starting up…"]);
  const problem = el("div.alert", { hidden: true });

  const page = el("div.page", {}, [
    el("div.page__head", {}, [
      el("div", {}, [
        el("h1.page__title", {}, ["Link a phone"]),
        el("p.page__hint", {}, ["The code changes every few seconds. Scan whichever one is on screen."]),
      ]),
      el("button.btn.btn--ghost", { type: "button", onclick: () => go("sessions") }, ["Back to phones"]),
    ]),

    el("div.qr", {}, [
      // Before the code, not after it. Somebody about to scan is the last
      // person who can decide not to, and a ban cannot be undone.
      el("div.qr__warning", {}, [
        el("b", {}, ["Only link a number kept for this purpose."]),
        "Numbers on the WhatsApp Business Platform must not be linked here — the link breaks WhatsApp's terms and a ban is permanent.",
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
  ]);

  clear(root).append(page);

  let shownQr = "";
  let stopped = false;

  async function poll() {
    if (stopped) return;
    let data;
    try {
      data = await api(`/api/sessions/${state.sessionId}/qr`);
      problem.hidden = true;
    } catch (error) {
      problem.hidden = false;
      clear(problem).append(error.message);
      return;
    }

    const look = statusOf(data.status);
    status.textContent = look.text;

    if (data.status === "ready") {
      stopped = true;
      stopTimers();
      // Nothing left to scan, so the code goes rather than sitting there
      // inviting a second phone at a session that already has one.
      clear(frame).replaceWith(connected(data));
      status.textContent = "";
      loadSessions();
      return;
    }

    if (data.status === "banned" || data.status === "disconnected") {
      stopped = true;
      stopTimers();
      clear(frame).append(
        el("div.qr__pending", {}, [
          data.status === "banned" ? "This number has been banned." : "This phone disconnected.",
        ])
      );
      problem.hidden = false;
      clear(problem).append(
        data.last_error || "WhatsApp ended the link. A banned number cannot be recovered."
      );
      loadSessions();
      return;
    }

    if (data.qr_data_url && data.qr_data_url !== shownQr) {
      shownQr = data.qr_data_url;
      clear(frame).append(el("img.qr__img", { src: data.qr_data_url, alt: "QR code to link a phone" }));
    }
  }

  function connected(data) {
    const session = sessionById(state.sessionId);
    const number = withPlus(data.phone_number || session?.phone_number);
    return el("div.qr__connected", {}, [
      el("div", {}, [number ? `Connected as ${number}` : "Connected"]),
      el(
        "button.btn",
        { type: "button", style: "margin-top:14px", onclick: () => openChats(state.sessionId) },
        ["Open chats"]
      ),
    ]);
  }

  poll();
  every(POLL_QR_MS, poll);
}

/* -------------------------------------------------------- screen 3: chats */

function openChats(id) {
  if (!id) return;
  go("chats", { sessionId: id, conversationId: null, conversations: [], messages: [] });
}

function renderChats() {
  const convs = el("div.convs", {}, [el("div.loading", {}, ["Loading…"])]);
  const thread = el("div.thread");
  const layout = el("div.chats", {}, [convs, thread]);

  clear(root).append(layout);
  renderThread(thread);

  loadConversations().then(() => paintConversations(convs, thread));
  every(POLL_CHAT_MS, async () => {
    await loadConversations();
    paintConversations(convs, thread);
    if (state.conversationId) {
      await loadMessages(state.conversationId);
      renderThread(thread, { keepScroll: true });
    }
  });

  async function loadConversations() {
    try {
      const payload = await api(`/api/conversations?session_id=${encodeURIComponent(state.sessionId)}`);
      // Sorted here rather than trusted from the wire: the list is only useful
      // newest-first, and the route does not promise an order.
      state.conversations = asList(payload, "conversations").sort(
        (a, b) => new Date(b.last_message_at || 0) - new Date(a.last_message_at || 0)
      );
      state.error = "";
    } catch (error) {
      state.error = error.message;
    }
  }
}

function conversationTitle(conversation) {
  return (
    conversation.subject ||
    conversation.contact?.display_name ||
    conversation.contact?.profile_name ||
    conversation.display_name ||
    conversation.profile_name ||
    withPlus(conversation.contact?.wa_id || conversation.wa_id) ||
    `Chat #${conversation.id}`
  );
}

const conversationWaId = (conversation) => conversation.contact?.wa_id || conversation.wa_id || "";

function paintConversations(convs, thread) {
  clear(convs);

  if (state.error) convs.append(el("div.alert", {}, [state.error]));

  if (!state.conversations.length) {
    convs.append(el("div.empty", {}, ["No chats yet. They appear as messages arrive."]));
    return;
  }

  for (const conversation of state.conversations) {
    convs.append(
      el(
        "button.conv",
        {
          type: "button",
          class: String(conversation.id) === String(state.conversationId) ? "is-active" : "",
          onclick: () => selectConversation(conversation.id, thread),
        },
        [
          el("div.conv__name", {}, [
            conversation.is_group ? el("span.chip--group", {}, ["Group"]) : null,
            el("span", {}, [conversationTitle(conversation)]),
          ]),
          el("span.conv__when", {}, [stamp(conversation.last_message_at)]),
          el("div.conv__last", {}, [
            conversation.last_message_preview || (conversation.last_message_kind ? `[${conversation.last_message_kind}]` : ""),
          ]),
          conversation.unread_count ? el("span.conv__unread", {}, [String(conversation.unread_count)]) : null,
        ]
      )
    );
  }
}

async function loadMessages(id) {
  try {
    const payload = await api(`/api/conversations/${id}/messages`);
    // Oldest first, which is reading order. Sorted here for the same reason
    // the conversations are: the route does not promise an order, and a thread
    // that renders backwards is worse than one that loads a moment later.
    state.messages = asList(payload, "messages").sort(
      (a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0)
    );
    state.error = "";
  } catch (error) {
    state.error = error.message;
    state.messages = [];
  }
}

async function selectConversation(id, thread) {
  state.conversationId = id;
  state.messages = [];
  renderThread(thread);
  await loadMessages(id);
  renderThread(thread);
  paintConversations(thread.parentElement.querySelector(".convs"), thread);
}

function renderThread(thread, { keepScroll = false } = {}) {
  const conversation = state.conversations.find((c) => String(c.id) === String(state.conversationId));

  if (!conversation) {
    clear(thread).append(el("div.empty", {}, ["Select a chat on the left."]));
    return;
  }

  const messages = el("div.thread__messages");
  const previous = thread.querySelector(".thread__messages");
  // "At the bottom" means the newest message is on screen; a reader scrolled
  // up to something older should not be yanked back by a poll.
  const wasAtBottom =
    !previous || previous.scrollTop + previous.clientHeight >= previous.scrollHeight - 60;

  for (const message of state.messages) messages.append(bubble(message, conversation));

  if (!state.messages.length) {
    messages.append(el("div.empty", {}, ["No messages in this chat yet."]));
  }

  clear(thread).append(
    el("div.thread__head", {}, [
      conversation.is_group ? el("span.chip--group", {}, ["Group"]) : null,
      el("div", {}, [
        el("div.thread__name", {}, [conversationTitle(conversation)]),
        el("div.thread__sub", {}, [
          conversation.is_group
            ? "Several people write in this chat"
            : withPlus(conversationWaId(conversation)),
        ]),
      ]),
    ]),
    messages,
    composer(conversation, thread)
  );

  // Newest at the bottom, so that is where the thread opens.
  if (!keepScroll || wasAtBottom) messages.scrollTop = messages.scrollHeight;
  else messages.scrollTop = previous.scrollTop;
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

  if (message.reply_to) {
    node.append(
      el("div.msg__quote", {}, [
        message.reply_to.body || `[${message.reply_to.kind || "message"}]`,
      ])
    );
  }

  if (message.media_id) node.append(attachment(message));

  if (message.body) node.append(el("div.msg__body", {}, [message.body]));
  else if (!message.media_id) node.append(el("div.msg__body", {}, [`[${message.kind || "message"}]`]));

  if (message.status === "failed" && message.error_detail) {
    node.append(el("div.msg__error", {}, [message.error_detail]));
  }

  node.append(
    el("div.msg__meta", {}, [
      stamp(message.created_at),
      outbound && message.status ? ` · ${message.status}` : "",
    ])
  );

  const reactions = Object.values(message.reactions || {}).filter(Boolean);
  if (reactions.length) {
    node.append(
      el(
        "div.msg__reactions",
        {},
        reactions.map((emoji) => el("span.reaction", {}, [emoji]))
      )
    );
  }

  return node;
}

function attachment(message) {
  const url = `/api/media/${message.media_id}`;
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

function composer(conversation, thread) {
  const session = sessionById(state.sessionId);
  if (session && session.status !== "ready") {
    return el("div.composer.composer--locked", {}, [
      `This phone is ${statusOf(session.status).text.toLowerCase()} — messages cannot be sent until it is ready.`,
    ]);
  }

  const input = el("textarea.composer__input", {
    rows: 1,
    placeholder: "Write a message…",
    maxlength: String(MAX_BODY),
  });
  const send = el("button.btn", { type: "button" }, ["Send"]);

  async function submit() {
    const body = input.value.trim();
    if (!body) return;

    send.disabled = true;
    const label = send.textContent;
    send.textContent = "Sending…";
    try {
      await api("/api/send", {
        method: "POST",
        body: {
          session_id: state.sessionId,
          to: conversationWaId(conversation),
          kind: "text",
          body,
        },
      });
      input.value = "";
      // Refetched rather than guessed: the row the server wrote carries the id
      // and status a locally invented bubble would not have.
      await loadMessages(conversation.id);
      renderThread(thread);
    } catch (error) {
      send.disabled = false;
      send.textContent = label;
      const problem = el("div.alert", {}, [error.message]);
      thread.querySelector(".thread__messages")?.append(problem);
      setTimeout(() => problem.remove(), 6000);
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
  return bar;
}

/* -------------------------------------------------------------------- boot */

async function boot() {
  await loadSessions();
  // Opening straight into the chats of the one ready phone saves a click on
  // the common setup, which is a single linked SIM.
  const ready = state.sessions.filter((s) => s.status === "ready");
  if (ready.length === 1) {
    openChats(ready[0].id);
    return;
  }
  go("sessions");
}

boot().catch((error) => {
  clear(root).append(el("div.page", {}, [el("div.alert", {}, [`The panel could not start: ${error.message}`])]));
  console.error("[wa-qr] boot failed:", error);
});
