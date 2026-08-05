/**
 * The things a thread needs beyond reading and replying.
 *
 * A lightbox, reactions, search, stars, a contact panel and forwarding — the
 * same seven the Cloud API panel has, brought over so an agent moving between
 * the two screens does not have to learn a second set of habits. Reactions
 * matter more here than there: the alots gateway refuses to *send* them, so on
 * the Cloud side the button could only ever be missing. On a QR-linked phone it
 * works, and this is the only place in the product where it can.
 *
 * Everything lives in this file on purpose. app.js is edited by more than one
 * session at a time, so this takes three small hooks from it and owns the rest
 * itself — most of it through one delegated listener on the thread rather than
 * a handler tied to every bubble, which also means a repaint cannot leave a
 * stale listener behind.
 *
 * Nothing a customer wrote is ever put through innerHTML. Message bodies,
 * contact names, filenames and group subjects were all typed by somebody
 * outside the company; they are only ever text nodes.
 */

/* ------------------------------------------------------------------ context */

/**
 * What app.js lends this module: its DOM helpers, its state, and the few
 * functions that redraw things. Passed in rather than imported, because the two
 * files would otherwise import each other and a circular import in plain ES
 * modules leaves whichever `const` loses the race undefined at call time.
 */
let ctx = null;

/** How many emoji the hover bar offers. WhatsApp's own six, in its own order. */
const REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"];

/** Pages of history to walk back through when jumping to a search result. */
const JUMP_PAGES = 12;

/** Which optional routes this server actually answers. Filled in at install. */
const has = { search: false, starred: false };

/* ------------------------------------------------------------------ helpers */

/**
 * Its own, rather than app.js's — that file has no debounce, and adding one
 * there would be a change to a file another session is editing for the sake of
 * four lines.
 */
function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

const isImage = (message) => {
  const mime = String(message.media_mime || "").toLowerCase();
  return (
    message.media_downloaded !== false &&
    (message.media_url || message.media_id) &&
    (mime.startsWith("image/") || ["image", "sticker"].includes(message.kind))
  );
};

/** Every picture currently loaded in the open thread, in reading order. */
const imagesInThread = () => ctx.state.messages.filter(isImage);

const inlineUrl = (message) =>
  ctx.onApi(message.media_inline_url || `api/media/${message.media_id}/inline`);

const downloadUrl = (message) =>
  ctx.onApi(message.media_url || `api/media/${message.media_id}`);

const messageById = (id) =>
  ctx.state.messages.find((m) => String(m.id) === String(id)) || null;

/** A one-line description of a message, for a search row or a forward preview. */
function summarise(message) {
  if (message.body) return message.body;
  if (message.media_name) return message.media_name;
  return `[${message.kind || "message"}]`;
}

/**
 * A POST to a route the other half of this service may not have deployed yet.
 *
 * The two halves land separately, so for a while a button here can be correct
 * and still have nothing to talk to. A 404 is reported as "not on this server
 * yet" rather than as a failure of the thing the agent was trying to do.
 */
async function action(path, body) {
  try {
    return await ctx.api(path, { method: "POST", body });
  } catch (error) {
    if (/HTTP 404/.test(error.message)) {
      throw new Error("This is not available on the server yet.");
    }
    throw error;
  }
}

/* ---------------------------------------------------------------- lightbox */

let lightbox = null;

/**
 * A picture at the size it was sent, with the rest of the conversation's
 * pictures either side of it.
 *
 * The inline URL, never the download one. The download route flattens
 * everything to application/octet-stream with nosniff — correct for a file a
 * stranger sent, and fatal for a photograph, because nosniff is precisely the
 * instruction not to work out that those bytes are a JPEG. An <img> pointing
 * there renders nothing at all.
 */
function openLightbox(message) {
  const { el, clear } = ctx;
  closeLightbox();

  const shots = imagesInThread();
  let at = Math.max(0, shots.findIndex((m) => String(m.id) === String(message.id)));

  const picture = el("img.lb__img", { alt: "" });
  const caption = el("div.lb__caption");
  const counter = el("div.lb__counter");

  const prev = el("button.lb__nav.lb__nav--prev", { type: "button", title: "Previous picture" }, ["‹"]);
  const next = el("button.lb__nav.lb__nav--next", { type: "button", title: "Next picture" }, ["›"]);
  const save = el("a.lb__save", { title: "Download this picture" }, ["Download"]);
  const shut = el("button.lb__close", { type: "button", title: "Close" }, ["×"]);

  function show(index) {
    at = (index + shots.length) % shots.length;
    const current = shots[at];
    picture.src = inlineUrl(current);
    picture.alt = current.media_name || "";
    // download, not inline: this one is meant to land on disk with its own name.
    save.href = downloadUrl(current);
    save.download = current.media_name || "";
    clear(caption).append(current.body || current.media_name || "");
    clear(counter).append(shots.length > 1 ? `${at + 1} of ${shots.length}` : "");
    prev.hidden = next.hidden = shots.length < 2;
  }

  const onKey = (event) => {
    if (event.key === "Escape") return closeLightbox();
    if (event.key === "ArrowLeft") return show(at - 1);
    if (event.key === "ArrowRight") return show(at + 1);
  };

  prev.addEventListener("click", () => show(at - 1));
  next.addEventListener("click", () => show(at + 1));
  shut.addEventListener("click", closeLightbox);

  const stage = el("div.lb__stage", {}, [picture]);
  const backdrop = el("div.lb", {}, [
    el("div.lb__bar", {}, [counter, save, shut]),
    prev,
    stage,
    next,
    caption,
  ]);

  // Only the backdrop closes. Clicking the picture itself is how somebody
  // steadies it to look closer, and having that dismiss it is maddening.
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop || event.target === stage) closeLightbox();
  });

  document.addEventListener("keydown", onKey, true);
  document.body.append(backdrop);
  lightbox = { node: backdrop, onKey };
  show(at);
}

function closeLightbox() {
  if (!lightbox) return;
  document.removeEventListener("keydown", lightbox.onKey, true);
  lightbox.node.remove();
  lightbox = null;
}

/* ------------------------------------------------------------ voice notes */

/** The one that is playing, so starting another stops it. */
let nowPlaying = null;

const clock = (seconds) => {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/**
 * A voice note, drawn rather than left to the browser.
 *
 * `<audio controls>` renders the platform's own widget: on this panel's dark
 * theme that is a white pill with a ⋯ menu offering "Playback speed", sitting
 * in the middle of the conversation looking like something had gone wrong. It
 * also ignores every colour on the page and cannot be made to match one.
 *
 * So the same audio element does the work with `controls` off and this draws
 * the part people see: one button, a bar that can be dragged, and how long is
 * left. 1,434 of the messages on these phones are voice notes — it is the
 * second most common thing a customer sends after text.
 */
export function voiceNote(message, src) {
  const { el, clear } = ctx;

  const audio = new Audio();
  audio.preload = "metadata";
  audio.src = src;

  const play = el("button.voice__play", { type: "button", title: "Play" }, ["▶"]);
  const fill = el("div.voice__fill");
  const track = el("div.voice__track", {}, [fill]);
  const time = el("div.voice__time", {}, ["0:00"]);

  const paint = () => {
    const total = Number.isFinite(audio.duration) ? audio.duration : 0;
    fill.style.width = total ? `${(audio.currentTime / total) * 100}%` : "0%";
    // Counts down while playing and shows the length when idle — the same way
    // WhatsApp does, and the question being asked is "how much is left".
    time.textContent = audio.paused ? clock(total) : clock(total - audio.currentTime);
  };

  audio.addEventListener("loadedmetadata", paint);
  audio.addEventListener("timeupdate", paint);
  audio.addEventListener("ended", () => {
    audio.currentTime = 0;
    play.textContent = "▶";
    play.title = "Play";
    nowPlaying = null;
    paint();
  });
  audio.addEventListener("pause", () => {
    play.textContent = "▶";
    play.title = "Play";
    paint();
  });
  audio.addEventListener("play", () => {
    play.textContent = "❚❚";
    play.title = "Pause";
  });

  play.addEventListener("click", () => {
    if (!audio.paused) return audio.pause();
    // Two voice notes at once is nobody's intention, and on a thread of forty
    // it is easy to do by accident.
    if (nowPlaying && nowPlaying !== audio) nowPlaying.pause();
    nowPlaying = audio;
    audio.play().catch(() => {
      clear(time).append("Could not play");
    });
  });

  // Dragging the bar, including the drag that starts as a click.
  const seek = (event) => {
    const box = track.getBoundingClientRect();
    if (!box.width || !Number.isFinite(audio.duration)) return;
    const at = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    audio.currentTime = at * audio.duration;
    paint();
  };
  track.addEventListener("pointerdown", (event) => {
    track.setPointerCapture(event.pointerId);
    seek(event);
  });
  track.addEventListener("pointermove", (event) => {
    if (track.hasPointerCapture(event.pointerId)) seek(event);
  });

  return el("div.voice", {}, [play, track, time]);
}

/* --------------------------------------------------------------- reactions */

/**
 * The emoji bar that appears on a bubble.
 *
 * Built once per bubble rather than on hover, because building it on hover
 * means measuring and positioning it against a list that is scrolling. CSS
 * decides when it is visible; this only decides what it says.
 */
function reactionBar(message) {
  const { el } = ctx;
  // Nothing to decorate yet. An outbound message sits queued without a wamid
  // until the phone confirms it, and a reaction names the message it belongs
  // to by that id — so until it arrives there is no message to point at.
  if (!message.wamid) return null;

  const bar = el("div.msg__react", {});

  for (const emoji of REACTIONS) {
    bar.append(
      el("button.msg__react-btn", {
        type: "button",
        title: `React with ${emoji}`,
        "data-emoji": emoji,
        "data-act": "react",
      }, [emoji])
    );
  }

  // Taking a reaction back is sending an empty one, which is how WhatsApp
  // itself models it — there is no separate "unreact".
  bar.append(
    el("button.msg__react-btn.msg__react-btn--clear", {
      type: "button",
      title: "Remove my reaction",
      "data-emoji": "",
      "data-act": "react",
    }, ["✕"])
  );

  return bar;
}

async function react(message, emoji, node) {
  const conversation = ctx.activeConversation();
  if (!conversation) return;

  try {
    // WhatsApp's own id, not ours. A reaction decorates a message on the
    // phone, and the phone has never heard of our row numbers.
    await action("api/actions/react", {
      session_id: conversation.session_id,
      wamid: message.wamid,
      emoji,
    });
    // Refetched rather than guessed: which of the two parties a reaction is
    // attributed to is the server's business, and a locally invented one would
    // sit under the wrong name until the next poll corrected it.
    await ctx.loadMessages(ctx.state.conversationId);
    ctx.paintMessages();
  } catch (error) {
    node?.append(ctx.el("span.msg__error-note", {}, [error.message]));
  }
}

/* ------------------------------------------------------------------ search */

/**
 * Finding a message, in this chat or in every chat.
 *
 * Two modes in one dialog rather than two dialogs: the question is the same
 * one, and an agent who searched a chat and found nothing almost always wants
 * to widen it rather than start again somewhere else.
 */
function openSearch({ scoped = true } = {}) {
  const { el, clear, dialog } = ctx;

  const field = el("input.dlg__input", {
    type: "search",
    placeholder: scoped ? "Find in this chat" : "Find in every chat",
  });
  const everywhere = el("input", { type: "checkbox", checked: !scoped });
  const results = el("div.srch__rows");
  const note = el("div.srch__note", {}, ["Type at least two characters."]);

  const box = dialog({
    title: "Search messages",
    wide: true,
    body: el("div.srch", {}, [
      field,
      el("label.srch__scope", {}, [everywhere, el("span", {}, ["Search every chat, not only this one"])]),
      note,
      results,
    ]),
  });

  let token = 0;

  async function run() {
    const term = field.value.trim();
    clear(results);

    if (term.length < 2) {
      clear(note).append("Type at least two characters.");
      return;
    }

    const mine = ++token;
    clear(note).append("Searching…");

    const here = ctx.activeConversation();
    const query = new URLSearchParams({ q: term, limit: "100" });
    // The route narrows by phone, not by chat. Asking for one phone's worth is
    // as close as it gets on this side; the chat itself is picked out below.
    if (!everywhere.checked && here) query.set("session_id", String(here.session_id));

    let rows;
    try {
      rows = ctx.asList(await ctx.api(`api/messages/search?${query}`), "messages");
    } catch (error) {
      if (mine !== token) return;
      clear(note).append(
        /HTTP 404/.test(error.message)
          ? "Search is not available on the server yet."
          : error.message
      );
      return;
    }

    // A slower earlier search must not overwrite a faster later one.
    if (mine !== token) return;

    const capped = rows.length >= 100;
    if (!everywhere.checked && here) {
      rows = rows.filter((r) => String(r.conversation_id) === String(here.id));
    }

    clear(note).append(
      rows.length ? `${rows.length} found` : "Nothing matched.",
      // Said rather than hidden. The server answers with the hundred most
      // recent matches across the phone and this narrows them to one chat
      // afterwards, so an older match in this chat can be sitting behind a
      // hundred newer ones somewhere else — and silently showing fewer results
      // than exist is the kind of thing nobody notices until it matters.
      capped ? " · the server's newest 100 matches; narrow the words to see older ones" : ""
    );

    for (const row of rows) {
      const conversation = ctx.state.conversations.find(
        (c) => String(c.id) === String(row.conversation_id)
      );
      // The route names the contact itself, which is the better answer: a chat
      // that is not in the loaded list has no title on this side at all.
      const where =
        row.contact?.name ||
        (conversation ? ctx.conversationTitle(conversation) : `Chat #${row.conversation_id}`);

      const rowNode = el("button.srch__row", { type: "button" }, [
        el("div.srch__line", {}, [
          el("span.srch__where", {}, [where]),
          el("span.srch__when", {}, [ctx.stamp(row.created_at)]),
        ]),
        el("div.srch__text", {}, [summarise(row)]),
      ]);

      rowNode.addEventListener("click", async () => {
        box.close();
        await jumpTo(row.conversation_id, row.id);
      });

      results.append(rowNode);
    }
  }

  field.addEventListener("input", debounce(run, 220));
  everywhere.addEventListener("change", run);
  queueMicrotask(() => field.focus());
  return box;
}

/**
 * Opens the chat a message is in and puts that message on screen.
 *
 * The thread loads newest-first a page at a time, so a result from March is not
 * in the first page and often not in the tenth. It pages back until the message
 * is there or the chat runs out — bounded, because a chat with eight thousand
 * messages in it would otherwise pull all of them to reach the first one.
 */
async function jumpTo(conversationId, messageId) {
  if (String(conversationId) !== String(ctx.state.conversationId)) {
    await ctx.selectConversation(conversationId);
  }

  for (let page = 0; page < JUMP_PAGES; page += 1) {
    if (messageById(messageId)) break;
    if (!ctx.state.canLoadOlder) break;
    // eslint-disable-next-line no-await-in-loop -- each page decides the next
    const added = await ctx.loadOlderMessages();
    if (!added) break;
  }

  ctx.paintMessages({ keepScroll: true });

  const target = ctx.ui.thread.querySelector(`[data-message-id="${CSS.escape(String(messageId))}"]`);
  if (!target) return;

  target.scrollIntoView({ block: "center" });
  target.classList.add("msg--found");
  setTimeout(() => target.classList.remove("msg--found"), 2200);
}

/* ----------------------------------------------------------------- starred */

async function toggleStar(messageId, starred) {
  await action(`api/messages/${Number(messageId)}/star`, { starred });
  await ctx.loadMessages(ctx.state.conversationId);
  ctx.paintMessages();
}

function openStarred() {
  const { el, clear, dialog } = ctx;
  const rows = el("div.srch__rows");
  const note = el("div.srch__note", {}, ["Loading…"]);

  const box = dialog({
    title: "Starred messages",
    wide: true,
    body: el("div.srch", {}, [note, rows]),
  });

  ctx
    .api("api/messages/starred?limit=100")
    .then((payload) => {
      const found = ctx.asList(payload, "messages");
      clear(note).append(
        found.length
          ? `${found.length} starred`
          : "Nothing is starred yet. Star a message from the ⋯ menu on its bubble."
      );

      for (const row of found) {
        const conversation = ctx.state.conversations.find(
          (c) => String(c.id) === String(row.conversation_id)
        );
        const rowNode = el("button.srch__row", { type: "button" }, [
          el("div.srch__line", {}, [
            el("span.srch__where", {}, [
              conversation ? ctx.conversationTitle(conversation) : `Chat #${row.conversation_id}`,
            ]),
            el("span.srch__when", {}, [ctx.stamp(row.created_at)]),
          ]),
          el("div.srch__text", {}, [summarise(row)]),
        ]);
        rowNode.addEventListener("click", async () => {
          box.close();
          await jumpTo(row.conversation_id, row.id);
        });
        rows.append(rowNode);
      }
    })
    .catch((error) =>
      clear(note).append(
        /HTTP 404/.test(error.message)
          ? "Starred messages are not available on the server yet."
          : error.message
      )
    );

  return box;
}

/* ----------------------------------------------------------------- forward */

function openForward(message) {
  const { el, clear, dialog } = ctx;

  const chosen = new Set();
  const filter = el("input.dlg__input", { type: "search", placeholder: "Find a chat" });
  const list = el("div.fwd__rows");
  const problem = el("div.alert", { hidden: true });
  const send = el("button.btn", { type: "button", disabled: true }, ["Forward"]);
  const cancel = el("button.btn.btn--ghost", { type: "button" }, ["Cancel"]);

  function paint() {
    const term = filter.value.trim().toLowerCase();
    clear(list);

    const rows = ctx.state.conversations.filter((c) => {
      if (String(c.id) === String(message.conversation_id)) return false;
      if (!term) return true;
      return ctx.conversationTitle(c).toLowerCase().includes(term);
    });

    if (!rows.length) {
      list.append(el("div.empty", {}, ["No chat matches that."]));
      return;
    }

    for (const conversation of rows) {
      const title = ctx.conversationTitle(conversation);
      const phone = ctx.sessionById(conversation.session_id);
      const tick = el("input", { type: "checkbox", checked: chosen.has(conversation.id) });

      tick.addEventListener("change", () => {
        if (tick.checked) chosen.add(conversation.id);
        else chosen.delete(conversation.id);
        send.disabled = !chosen.size;
        send.textContent = chosen.size > 1 ? `Forward to ${chosen.size}` : "Forward";
      });

      list.append(
        el("label.fwd__row", {}, [
          tick,
          ctx.avatarFor(conversation, title, { small: true }),
          el("div.fwd__who", {}, [
            el("div.fwd__name", {}, [title]),
            el("div.fwd__sub", {}, [phone ? `on ${ctx.sessionName(phone)}` : ""]),
          ]),
        ])
      );
    }
  }

  const box = dialog({
    title: "Forward this message",
    wide: true,
    body: el("div.fwd", {}, [
      el("div.fwd__preview", {}, [summarise(message)]),
      filter,
      list,
      problem,
    ]),
    actions: [cancel, send],
  });

  cancel.addEventListener("click", () => box.close());
  filter.addEventListener("input", debounce(paint, 150));

  send.addEventListener("click", async () => {
    send.disabled = true;
    send.textContent = "Forwarding…";
    problem.hidden = true;

    // One call per recipient, because the route takes one. Sent from the phone
    // that owns the target chat, not from the one the message came in on — a
    // customer should hear from the number they already know.
    const failures = [];
    for (const conversationId of chosen) {
      const target = ctx.state.conversations.find((c) => String(c.id) === String(conversationId));
      if (!target) continue;
      try {
        // eslint-disable-next-line no-await-in-loop -- one at a time on purpose
        await action("api/actions/forward", {
          session_id: target.session_id,
          wamid: message.wamid,
          to_wa_id: ctx.conversationWaId(target),
        });
      } catch (error) {
        failures.push(`${ctx.conversationTitle(target)}: ${error.message}`);
      }
    }

    if (!failures.length) {
      box.close();
      return;
    }

    // Named, not counted. "2 failed" leaves the agent to work out which two,
    // and forwarding the same message twice to the wrong person is the cost of
    // guessing wrong.
    send.disabled = false;
    send.textContent = "Forward";
    problem.hidden = false;
    clear(problem).append(
      el("div", {}, [`Could not forward to ${failures.length} of ${chosen.size}:`]),
      ...failures.map((line) => el("div", {}, [line]))
    );
  });

  paint();
  queueMicrotask(() => filter.focus());
  return box;
}

/* ---------------------------------------------------------- contact panel */

let contactOpen = false;

/** Toggles the panel on the right of the thread. */
function toggleContact() {
  contactOpen = !contactOpen;
  paintContact();
}

function paintContact() {
  const { el, clear } = ctx;
  const existing = document.querySelector(".contactp");

  if (!contactOpen) {
    existing?.remove();
    document.body.classList.remove("has-contact");
    return;
  }

  // Closing the last chat leaves nothing to describe, and a panel still
  // describing the previous one is worse than no panel.
  const conversation = ctx.activeConversation();
  if (!conversation) {
    existing?.remove();
    return;
  }

  const title = ctx.conversationTitle(conversation);
  const phone = ctx.sessionById(conversation.session_id);

  // Everything loaded in the thread that is a picture. Deliberately only what
  // is loaded: a grid that quietly fetched the whole chat's media would pull
  // months of it to draw twelve thumbnails, and "Load earlier messages" already
  // means the same thing here as it does in the thread.
  const shots = imagesInThread();
  const files = ctx.state.messages.filter(
    (m) => (m.media_url || m.media_id) && m.media_downloaded !== false && !isImage(m)
  );

  const panel = el("aside.contactp", {}, [
    el("div.contactp__top", {}, [
      el("div.contactp__title", {}, ["Contact"]),
      el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: toggleContact, title: "Close" }, ["×"]),
    ]),
    el("div.contactp__who", {}, [
      ctx.avatarFor(conversation, title),
      el("div.contactp__name", {}, [title]),
      el("div.contactp__num", {}, [
        conversation.is_group
          ? "Group chat"
          : ctx.withPlus(ctx.conversationWaId(conversation)) || "No number on record",
      ]),
      phone ? el("div.contactp__on", {}, [`On ${ctx.sessionName(phone)}`]) : null,
    ]),
    el("div.contactp__section", {}, [
      el("div.contactp__label", {}, [`Shared pictures (${shots.length})`]),
      shots.length
        ? el(
            "div.contactp__grid",
            {},
            shots.slice(-24).reverse().map((m) => {
              const cell = el("img.contactp__cell", { src: inlineUrl(m), alt: "", loading: "lazy" });
              cell.addEventListener("click", () => openLightbox(m));
              return cell;
            })
          )
        : el("div.contactp__none", {}, ["None in what is loaded."]),
    ]),
    el("div.contactp__section", {}, [
      el("div.contactp__label", {}, [`Shared files (${files.length})`]),
      files.length
        ? el(
            "div.contactp__files",
            {},
            files.slice(-15).reverse().map((m) =>
              el("a.contactp__file", { href: downloadUrl(m), target: "_blank", rel: "noopener" }, [
                ctx.icon("file", { size: 15 }),
                el("span", {}, [m.media_name || m.kind || "File"]),
                el("small", {}, [ctx.formatBytes(m.media_size)]),
              ])
            )
          )
        : el("div.contactp__none", {}, ["None in what is loaded."]),
    ]),
  ]);

  if (existing) existing.replaceWith(panel);
  else ctx.ui.thread.after(panel);
  document.body.classList.add("has-contact");
}

/* -------------------------------------------------------------- bubble menu */

function openBubbleMenu(message, anchor) {
  const { el } = ctx;
  document.querySelector(".bmenu")?.remove();

  const menu = el("div.bmenu", {});
  const item = (label, run) => {
    const node = el("button.bmenu__item", { type: "button" }, [label]);
    node.addEventListener("click", () => {
      menu.remove();
      run();
    });
    return node;
  };

  menu.append(
    item(message.starred ? "Remove star" : "Star this message", () =>
      toggleStar(message.id, !message.starred).catch((error) => window.console.warn(error.message))
    )
  );
  // Same reason as the reaction bar: append(null) writes "null" on screen.
  // A message still waiting for its id has nothing the phone can forward.
  if (message.wamid) menu.append(item("Forward…", () => openForward(message)));
  if (message.body) {
    menu.append(
      item("Copy text", () => navigator.clipboard?.writeText(message.body).catch(() => {}))
    );
  }

  const box = anchor.getBoundingClientRect();
  menu.style.top = `${box.bottom + 4}px`;
  menu.style.left = `${Math.max(8, box.right - 180)}px`;

  const away = (event) => {
    if (menu.contains(event.target)) return;
    menu.remove();
    document.removeEventListener("mousedown", away, true);
  };
  document.addEventListener("mousedown", away, true);
  document.body.append(menu);
}

/* ------------------------------------------------------------------- hooks */

/**
 * Everything a bubble gains: an id to be found by, a menu button, a star mark,
 * and the emoji bar.
 *
 * Called at the end of app.js's own bubble(), so nothing above is disturbed.
 */
export function decorateBubble(node, message) {
  if (!ctx) return node;

  node.dataset.messageId = String(message.id);

  if (message.starred) {
    node.append(ctx.el("span.msg__star", { title: "Starred" }, ["★"]));
  }

  node.append(
    ctx.el("button.msg__more", {
      type: "button",
      title: "More",
      "data-act": "menu",
    }, ["⋯"])
  );

  // Appended only if there is one. append(null) writes the literal text "null"
  // into the bubble — el() filters nulls out of its children, append does not,
  // and that difference has already put the word on this screen once.
  const bar = reactionBar(message);
  if (bar) node.append(bar);

  return node;
}

/**
 * The thread has just been redrawn.
 *
 * Called from messagesNode(), which both paint paths go through, so one line in
 * app.js covers the poll, a send, a retry and opening a chat. The contact panel
 * reads from the same messages the bubbles do and would otherwise still be
 * showing the pictures that had arrived when it was opened.
 */
export function notifyThreadPainted() {
  if (ctx && contactOpen) paintContact();
}

/** The buttons that belong in the thread's header. */
export function threadHeadExtras() {
  if (!ctx) return null;
  const { el } = ctx;

  const buttons = [];

  if (has.search) {
    buttons.push(
      el("button.btn.btn--ghost.btn--sm", {
        type: "button",
        title: "Search in this chat",
        onclick: () => openSearch({ scoped: true }),
      }, [ctx.icon("search", { size: 14 }), "Search"])
    );
  }
  if (has.starred) {
    buttons.push(
      el("button.btn.btn--ghost.btn--sm", {
        type: "button",
        title: "Starred messages",
        onclick: openStarred,
      }, ["★"])
    );
  }
  buttons.push(
    el("button.btn.btn--ghost.btn--sm", {
      type: "button",
      title: "Contact details",
      onclick: toggleContact,
    }, [ctx.icon("users", { size: 14 })])
  );

  return el("div.thread__tools", {}, buttons);
}

/**
 * Wires the module up once, and finds out what this server can actually do.
 *
 * The two halves of this service deploy separately, so a button here can be
 * finished while the route behind it is not. The two read-only routes are
 * probed — a GET that 404s costs nothing — and their buttons are simply absent
 * until the server grows them, rather than present and refusing.
 */
export async function installThreadExtras(context) {
  ctx = context;

  // One listener for the whole thread. A bubble is replaced on every poll, so a
  // handler bound to a bubble is a handler bound to something about to be
  // thrown away — and, in the capture phase, this also gets to a picture before
  // the img's own click handler does.
  ctx.ui.thread.addEventListener(
    "click",
    (event) => {
      const thumb = event.target.closest?.(".msg__thumb");
      const bubble = event.target.closest?.("[data-message-id]");
      if (thumb && bubble) {
        // Stops app.js's own onclick, which opens the picture in a bare tab.
        event.preventDefault();
        event.stopPropagation();
        const message = messageById(bubble.dataset.messageId);
        if (message) openLightbox(message);
        return;
      }

      const act = event.target.closest?.("[data-act]");
      if (!act || !bubble) return;
      const message = messageById(bubble.dataset.messageId);
      if (!message) return;

      if (act.dataset.act === "react") {
        event.preventDefault();
        react(message, act.dataset.emoji, bubble);
      } else if (act.dataset.act === "menu") {
        event.preventDefault();
        openBubbleMenu(message, act);
      }
    },
    true
  );

  const probe = async (path) => {
    try {
      await ctx.api(path);
      return true;
    } catch (error) {
      return !/HTTP 404/.test(error.message);
    }
  };

  const [search, starred] = await Promise.all([
    probe("api/messages/search?q=a&limit=1"),
    probe("api/messages/starred?limit=1"),
  ]);
  has.search = search;
  has.starred = starred;

  if (!search || !starred) {
    console.info(
      `[wa-qr] thread extras: search=${search ? "on" : "not deployed"} ` +
        `starred=${starred ? "on" : "not deployed"}`
    );
  }
}
