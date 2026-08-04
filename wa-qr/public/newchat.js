/**
 * Starting a conversation, and the screens that say what that costs.
 *
 * These two belong in one file because they are one decision. A QR-linked
 * number is somebody's personal WhatsApp account: no approved templates, no
 * rate limit agreed with Meta, no appeal worth the name. Messaging people who
 * did not write first is the single behaviour that gets such a number banned,
 * and this dialog is the only place in the panel where an agent does it. So the
 * phone's risk level is shown *inside* the dialog, next to the send button,
 * rather than left on a banner they scrolled past an hour ago.
 *
 * The numbers all come from `/api/risk`. None of them are counted here on
 * purpose: the server measures every window by when a message was **sent**, and
 * an earlier version that counted rows by when they were stored reported "68
 * new conversations" for a phone that had sent 22 — because the history import
 * had just written six months of them. Every freshly linked number was declared
 * at risk on the day it was linked, which is how a warning stops being read.
 *
 * Nothing here goes through innerHTML. Every number, name and message body is
 * something a person outside this company typed.
 */

/* ------------------------------------------------------------------ context */

/** What app.js lends this module. Passed in, so neither file imports the other. */
let ctx = null;

/** Risk is behaviour measured in days; it does not move in seconds. */
const RISK_POLL_MS = 60_000;

/** How long to wait after a keystroke before asking WhatsApp about a number. */
const CHECK_DEBOUNCE_MS = 500;

/** E.164: a country code and a subscriber number, never more than fifteen. */
const MIN_DIGITS = 8;
const MAX_DIGITS = 15;

const RISK_LOOK = {
  ok: { text: "Looks fine", cls: "risk--ok" },
  watch: { text: "Worth watching", cls: "risk--watch" },
  high: { text: "At risk of a ban", cls: "risk--high" },
};

/** Whether /api/newchat is deployed. Probed once; the two halves land apart. */
let canStartChats = null;

/** The last answer from /api/risk, by session id. */
let riskBySession = new Map();

/* ------------------------------------------------------------------ helpers */

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

const digitsOf = (text) => String(text || "").replace(/\D/g, "");

const notFound = (error) => /HTTP 404/.test(error?.message || "");

/**
 * What a message is, in words rather than in the library's vocabulary.
 *
 * The chat list printed the raw kind in brackets, so a poll, a missed call and
 * a message type this panel does not model yet all read as "[unknown]" — which
 * tells an agent nothing except that something is broken. Nothing here is
 * guessed: `unknown` really is unknown, and saying so plainly beats inventing a
 * name for it.
 */
const KIND_LABEL = {
  text: "",
  image: "Photo",
  video: "Video",
  audio: "Voice message",
  document: "Document",
  sticker: "Sticker",
  location: "Location",
  contacts: "Contact card",
  unknown: "Message not shown here",
};

export function kindLabel(kind) {
  const key = String(kind || "").toLowerCase();
  if (key in KIND_LABEL) return KIND_LABEL[key];
  // A kind nobody has mapped yet: its own name reads better than "unknown".
  return key ? key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : "";
}

/* -------------------------------------------------------------------- risk */

async function refreshRisk() {
  try {
    const rows = ctx.asList(await ctx.api("api/risk"), "risk");
    riskBySession = new Map(rows.map((row) => [Number(row.session_id), row]));
  } catch {
    // A level nobody can fetch is not worth an error on screen; the counting
    // still happens server-side either way.
  }
}

const riskFor = (sessionId) => riskBySession.get(Number(sessionId)) || null;

/** The small coloured word beside a phone. Null when nothing is known yet. */
export function riskChipFor(sessionId) {
  if (!ctx) return null;
  const row = riskFor(sessionId);
  if (!row) return null;

  const look = RISK_LOOK[row.level] || RISK_LOOK.ok;
  return ctx.el(
    "span.risk",
    {
      class: look.cls,
      // The reasons on hover, in full. They are sentences, and the chip is two
      // words — the whole explanation should not need another click.
      title: row.reasons?.length ? row.reasons.join("\n") : "Nothing about this number stands out.",
      onclick: (event) => {
        event.stopPropagation();
        openSafety(sessionId);
      },
    },
    [look.text]
  );
}

/* ---------------------------------------------------------- safety screen */

/**
 * Each figure, and what it means.
 *
 * The wording is the point. "newContacts24h: 31" is a fact an agent cannot act
 * on; "31 people you messaged first, today — this is the one WhatsApp bans
 * numbers for" is the same fact with the decision attached to it.
 */
const FIGURES = [
  {
    key: "newContacts24h",
    title: "People messaged first, today",
    why: "Conversations this phone started with somebody who had not written to it. This is the number WhatsApp acts on above all others — a personal account that starts many conversations a day looks like the accounts it bans.",
  },
  {
    key: "outbound24h",
    title: "Messages sent, today",
    why: "Everything sent from this handset in 24 hours, replies included. Answering people is not what gets a number banned, so a high figure here matters far less than the one above — but a handset sending hundreds a day is not a handset a person is holding.",
  },
  {
    key: "started7d",
    title: "Conversations started this week",
    why: "The same thing as the first figure, over seven days. It is the denominator for the one below: a share is not worth reading until there are enough conversations for it to mean something.",
  },
  {
    key: "ignoredShare",
    title: "Started and never answered",
    percent: true,
    why: "Of the conversations this number started this week, the share where the other person never replied. Being ignored at a high rate is how WhatsApp tells outreach apart from conversation — people answer someone they were expecting to hear from.",
  },
  {
    key: "failed24h",
    title: "Sends that failed today",
    why: "Messages the phone would not deliver. A few are normal — a number that is not on WhatsApp, a moment offline. Many at once is often the first visible sign that a number is already being restricted.",
  },
];

const figureValue = (signals, figure) => {
  const raw = Number(signals?.[figure.key] ?? 0);
  return figure.percent ? `${Math.round(raw * 100)}%` : raw.toLocaleString();
};

/** The Safety screen. `focusId` opens with one phone expanded. */
export function openSafety(focusId = null) {
  const { el, clear, dialog } = ctx;
  const body = el("div.sfty");
  const box = dialog({ title: "Number safety", wide: true, body });

  const paint = () => {
    clear(body).append(
      el("p.sfty__intro", {}, [
        "A QR-linked phone is a personal WhatsApp account. There are no approved templates behind it, " +
          "no rate limit agreed with Meta, and no appeal worth the name — when one is banned it is banned, " +
          "and every conversation on it goes with it. These are the figures WhatsApp's own behaviour is " +
          "judged on, counted from what this phone has actually sent.",
      ])
    );

    const rows = ctx.state.sessions;
    if (!rows.length) {
      body.append(el("div.empty", {}, ["No phone is linked yet."]));
      return;
    }

    for (const session of rows) {
      const row = riskFor(session.id);
      const look = RISK_LOOK[row?.level || "ok"];
      const signals = row?.signals || {};

      body.append(
        el("section.sfty__phone", { class: focusId && Number(focusId) === Number(session.id) ? "is-focus" : "" }, [
          el("div.sfty__head", {}, [
            el("div.sfty__name", {}, [ctx.sessionName(session)]),
            el("span.risk", { class: look.cls }, [look.text]),
          ]),

          // The reasons first, because they are the part that says what to do.
          row?.reasons?.length
            ? el("div.sfty__reasons", {}, row.reasons.map((r) => el("div.sfty__reason", {}, [r])))
            : el("div.sfty__reasons", {}, [
                el("div.sfty__reason.sfty__reason--calm", {}, [
                  "Nothing about how this number is being used stands out.",
                ]),
              ]),

          el(
            "div.sfty__grid",
            {},
            FIGURES.map((figure) =>
              el("div.sfty__fig", {}, [
                el("div.sfty__val", {}, [figureValue(signals, figure)]),
                el("div.sfty__title", {}, [figure.title]),
                el("div.sfty__why", {}, [figure.why]),
              ])
            )
          ),

          el("div.sfty__note", {}, [
            "Every window above is measured on when a message was sent, not on when this panel learned " +
              "of it — so importing a phone's history does not make it look busy.",
          ]),
        ])
      );
    }

    body.append(
      el("div.sfty__foot", {}, [
        "What is not here: blocks and reports. Those matter more than anything above and WhatsApp does " +
          "not show them to anyone. These figures can say a number is behaving the way banned numbers " +
          "behave; they cannot promise it is safe.",
      ])
    );

    body.querySelector(".is-focus")?.scrollIntoView({ block: "start" });
  };

  paint();
  refreshRisk().then(paint);
  return box;
}

/* -------------------------------------------------------------- new chat */

export function openNewChat() {
  const { el, clear, dialog } = ctx;

  /* ---- which phone ---- */

  const phoneSelect = el("select.field");
  const riskLine = el("div.nc__risk");

  const ready = ctx.state.sessions.filter((s) => s.status === "ready");
  for (const session of ready) {
    phoneSelect.append(el("option", { value: String(session.id) }, [ctx.sessionName(session)]));
  }
  if (!ready.length) {
    phoneSelect.append(el("option", { value: "" }, ["No phone is connected"]));
  }
  // The chat list's current filter is almost always the phone they mean.
  if (ctx.state.phoneFilter && ready.some((s) => String(s.id) === String(ctx.state.phoneFilter))) {
    phoneSelect.value = String(ctx.state.phoneFilter);
  }

  /* ---- who to ---- */

  const numberInput = el("input.field", {
    type: "tel",
    placeholder: "971501234567",
    autocomplete: "off",
  });
  const numberNote = el("div.nc__note", {}, ["Include the country code, without a plus or spaces."]);
  const messageBox = el("textarea.field.nc__body", {
    rows: 4,
    placeholder: "The first message. Say who you are — a stranger's first message is what gets reported.",
    maxlength: "4096",
  });

  const problem = el("div.alert", { hidden: true });
  const send = el("button.btn", { type: "button", disabled: true }, ["Start the chat"]);
  const cancel = el("button.btn.btn--ghost", { type: "button" }, ["Cancel"]);

  // Null until the server has answered for the number currently typed.
  let onWhatsApp = null;
  let checking = false;
  // The chat this number already has on this phone, if any.
  let existingId = null;

  function paintRisk() {
    const row = riskFor(phoneSelect.value);
    clear(riskLine);
    if (!row) return;

    const look = RISK_LOOK[row.level] || RISK_LOOK.ok;
    riskLine.className = `nc__risk ${look.cls}`;
    riskLine.append(
      el("span.risk", { class: look.cls }, [look.text]),
      el("div.nc__risk-why", {}, [
        row.level === "high"
          ? "Starting another conversation from this phone today is what gets numbers banned. Use a different one if you can."
          : row.level === "watch"
            ? "This phone has started a lot of conversations recently. Prefer a quieter one if you have it."
            : "Nothing about how this phone is being used stands out.",
      ]),
      el("button.nc__risk-more", { type: "button", onclick: () => openSafety(phoneSelect.value) }, [
        "See the figures",
      ])
    );
  }

  function refreshSendState() {
    const digits = digitsOf(numberInput.value);
    const valid = digits.length >= MIN_DIGITS && digits.length <= MAX_DIGITS;
    // A number the server has said is not on WhatsApp is the one case this
    // refuses outright. Everything else — no answer yet, no check on this
    // server — leaves the decision with the agent rather than blocking them.
    send.disabled =
      !valid || !phoneSelect.value || checking || onWhatsApp === false || Boolean(existingId);
  }

  /** Asks the phone whether this number is on WhatsApp at all, before sending. */
  const check = debounce(async () => {
    const digits = digitsOf(numberInput.value);
    onWhatsApp = null;

    if (digits.length < MIN_DIGITS || digits.length > MAX_DIGITS) {
      clear(numberNote).append(
        digits.length
          ? `${digits.length} digits — a number with its country code is ${MIN_DIGITS} to ${MAX_DIGITS}.`
          : "Include the country code, without a plus or spaces."
      );
      numberNote.className = "nc__note";
      refreshSendState();
      return;
    }
    if (!phoneSelect.value) return;

    checking = true;
    refreshSendState();
    clear(numberNote).append(`Checking ${ctx.withPlus(digits)} on WhatsApp…`);
    numberNote.className = "nc__note";

    const asked = digits;
    try {
      const answer = await ctx.api(
        `api/newchat/check?session_id=${encodeURIComponent(phoneSelect.value)}&phone=${encodeURIComponent(digits)}`
      );
      // The agent has typed on since this went out.
      if (asked !== digitsOf(numberInput.value)) return;

      existingId = answer?.existing_conversation_id || null;

      // A number on the Business Platform, refused before anything else. This
      // is the one that cannot be undone: linking or messaging one of the 21
      // verified numbers by QR risks a permanent ban on an account carrying
      // ~260 approved templates.
      if (answer?.guarded) {
        onWhatsApp = false;
        clear(numberNote).append(
          `${ctx.withPlus(digits)} is one of the company's WhatsApp Business Platform numbers. It must not be messaged from a QR-linked phone.`
        );
        numberNote.className = "nc__note nc__note--bad";
        return;
      }

      onWhatsApp = answer?.exists_on_whatsapp ?? null;

      // Already talking to this person on this phone. Better said now than
      // after a second thread appears beside the first one.
      if (existingId) {
        clear(numberNote).append(
          el("span", {}, [`${ctx.withPlus(digits)} already has a chat on this phone. `]),
          el("button.nc__risk-more", {
            type: "button",
            onclick: () => {
              box.close();
              ctx.selectConversation(existingId);
            },
          }, ["Open it"])
        );
        numberNote.className = "nc__note nc__note--ok";
        return;
      }

      if (onWhatsApp === true) {
        clear(numberNote).append(`${ctx.withPlus(digits)} is on WhatsApp.`);
        numberNote.className = "nc__note nc__note--ok";
      } else {
        clear(numberNote).append(
          `${ctx.withPlus(digits)} is not on WhatsApp. Sending to it would fail, and failed sends count against this phone.`
        );
        numberNote.className = "nc__note nc__note--bad";
      }
    } catch (error) {
      if (asked !== digitsOf(numberInput.value)) return;
      // Said plainly rather than passed off as "fine". The check is the whole
      // point of this field, and an agent should know when it did not happen.
      clear(numberNote).append(
        notFound(error)
          ? "This server cannot check numbers yet — send only if you are sure this one is right."
          : `Could not check this number: ${error.message}`
      );
      numberNote.className = "nc__note";
    } finally {
      checking = false;
      refreshSendState();
    }
  }, CHECK_DEBOUNCE_MS);

  numberInput.addEventListener("input", () => {
    onWhatsApp = null;
    existingId = null;
    refreshSendState();
    check();
  });
  phoneSelect.addEventListener("change", () => {
    paintRisk();
    onWhatsApp = null;
    existingId = null;
    refreshSendState();
    check();
  });

  const box = dialog({
    title: "New chat",
    wide: true,
    body: el("div.nc", {}, [
      // Said before anything is typed, not after it is sent. Filling this in
      // and then being told the route does not exist is a worse way to find out.
      canStartChats === false
        ? el("div.alert", {}, [
            "This server cannot start new chats yet. The rest of this dialog works, " +
              "but sending will be refused.",
          ])
        : null,
      el("label.nc__field", {}, [el("span", {}, ["Send from"]), phoneSelect]),
      riskLine,
      el("label.nc__field", {}, [el("span", {}, ["To this number"]), numberInput, numberNote]),
      el("label.nc__field", {}, [el("span", {}, ["First message"]), messageBox]),
      problem,
    ]),
    actions: [cancel, send],
  });

  cancel.addEventListener("click", () => box.close());

  send.addEventListener("click", async () => {
    const digits = digitsOf(numberInput.value);
    const body = messageBox.value.trim();
    if (!body) {
      problem.hidden = false;
      clear(problem).append("Write the first message — an empty one cannot be sent.");
      return;
    }

    send.disabled = true;
    send.textContent = "Starting…";
    problem.hidden = true;

    try {
      const answer = await ctx.api("api/newchat", {
        method: "POST",
        body: { session_id: Number(phoneSelect.value), phone: digits, first_message: body },
      });

      box.close();
      await ctx.refresh({ keepScroll: false });

      const id = answer?.conversation_id ?? answer?.conversation?.id ?? answer?.id;
      if (id) await ctx.selectConversation(id);
      refreshRisk();
    } catch (error) {
      send.disabled = false;
      send.textContent = "Start the chat";
      problem.hidden = false;
      // The server's own sentence, in full. A refusal here is the safety rule
      // explaining itself, and shortening it to "Forbidden" would throw away
      // the only part worth reading.
      clear(problem).append(
        notFound(error) ? "Starting a chat is not available on this server yet." : error.message
      );
    }
  });

  paintRisk();
  refreshSendState();
  queueMicrotask(() => numberInput.focus());
  return box;
}

/* ------------------------------------------------- chat list filter strip */

/**
 * Which chats are shown, beyond the text search app.js already does.
 *
 * Its own strip rather than more controls in the header: these two are answers
 * to "what have I not dealt with" and "what is mine", which is a different
 * question from "find me this chat".
 */
const filters = { unreadOnly: false, mineOnly: false };

/** True when a conversation survives this strip. app.js asks per row. */
export function passesFilters(conversation) {
  if (!ctx) return true;
  if (filters.unreadOnly && !conversation.unread_count) return false;
  if (filters.mineOnly && !isMine(conversation)) return false;
  return true;
}

/** Whether the phone a chat is on is assigned to whoever is signed in. */
function isMine(conversation) {
  const me = ctx.state.me?.agent_id;
  if (!me) return false;
  const session = ctx.state.sessions.find((s) => String(s.id) === String(conversation.session_id));
  return Boolean(session?.agents?.some((a) => Number(a.agent_id) === Number(me)));
}

/* ------------------------------------------------------------------- hooks */

/**
 * Two empty containers, handed to app.js the moment it asks and filled in later.
 *
 * app.js builds its whole shell in a module-level `const`, which runs when the
 * file is imported — long before boot() installs this module. Returning the
 * finished nodes there would mean returning them before there was a context to
 * build them from, and both would simply never appear.
 */
const slots = {
  newChat: document.createElement("span"),
  filters: document.createElement("div"),
};
slots.filters.className = "ncf";

/** The button above the chat list. */
export function newChatButton() {
  return slots.newChat;
}

export function filterStrip() {
  return slots.filters;
}

function fillSlots() {
  const { el } = ctx;

  slots.newChat.replaceChildren(
    el(
      "button.btn.btn--sm.nc__start",
      { type: "button", title: "Message a number for the first time", onclick: openNewChat },
      [ctx.icon("chat", { size: 13 }), "New chat"]
    )
  );

  const toggle = (key, label, title) => {
    const button = el("button.ncf__btn", { type: "button", title }, [label]);
    const paint = () => button.classList.toggle("is-on", filters[key]);
    button.addEventListener("click", () => {
      filters[key] = !filters[key];
      paint();
      ctx.paintConversations();
    });
    paint();
    return button;
  };

  slots.filters.replaceChildren(
    ...[
      toggle("unreadOnly", "Unread", "Only chats with messages nobody has read"),
      // Only worth offering to somebody who has phones assigned to them. An
      // admin with none would press it and watch the list empty.
      ctx.state.me?.agent_id ? toggle("mineOnly", "Mine", "Only the phones assigned to me") : null,
      el("button.ncf__btn.ncf__btn--safety", {
        type: "button",
        title: "How safe these numbers are",
        onclick: () => openSafety(),
      }, ["Safety"]),
    ].filter(Boolean)
  );
}

export async function installNewChat(context) {
  ctx = context;

  // Before anything is awaited: the shell is already on screen, and a strip
  // that appears a network round trip later reads as a glitch.
  fillSlots();

  await refreshRisk();
  setInterval(refreshRisk, RISK_POLL_MS);

  // Probed once so a button is not offered for a route that is not there yet —
  // the two halves of this service deploy separately. A failure that is not a
  // 404 is treated as "present but unhappy", which is the truthful reading.
  try {
    await ctx.api("api/newchat/check?phone=0");
    canStartChats = true;
  } catch (error) {
    canStartChats = !notFound(error);
  }
  if (!canStartChats) {
    console.info("[wa-qr] /api/newchat is not deployed yet — the New chat dialog will say so");
  }
}
