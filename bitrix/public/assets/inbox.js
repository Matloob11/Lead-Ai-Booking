/**
 * The agent inbox: conversation list on the left, thread on the right.
 *
 * Deliberately framework-free — the panel is served as static files from nginx,
 * so staying on plain ES modules keeps "deploy" equal to "copy the folder" with
 * no build step between an edit and the browser.
 *
 * Server rules the UI must mirror (see the API contract):
 *  - an agent sees every chat on their numbers, assigned or not; `assigned_agent`
 *    is ownership for transfers, never a list filter;
 *  - when `is_session_open` is false the composer is locked and only approved
 *    templates can reopen the 24h window;
 *  - transfer is admin-only.
 */

import { catalog, inbox, asList } from "./api.js";
import { bindFileSources, checkFile, openAttachmentDialog } from "./attach.js";
import { ensureSession } from "./bitrix-sso.js";
import { imagesInThread, openLightbox } from "./lightbox.js";
import { openNumbersAdmin } from "./numbers-admin.js";
import { InboxSocket } from "./realtime.js";
import { el, clear, dayKey, dayLabel, debounce, formatBytes, minutesUntil, modal, stamp, untilText, initials } from "./dom.js";
import { bindEmojiPicker } from "./emoji.js";
import { icon, iconForKind } from "./icons.js";

const PAGE_SIZE = 40;

const STATUS_TICK = {
  queued: { name: "clock", label: "queued" },
  sent: { name: "check", label: "sent" },
  delivered: { name: "checkDouble", label: "delivered" },
  read: { name: "checkDouble", label: "read", className: "tick--read" },
  failed: { name: "alert", label: "failed", className: "tick--failed" },
};

export function mountInbox(root, { me }) {
  const state = {
    me,
    numbers: [],
    numberFilter: "",
    search: "",
    conversations: [],
    activeId: null,
    messages: [],
    unreadAtOpen: 0,
    templates: new Map(), // numberId -> template[]
    loadingThread: false,
    connection: "connecting",
  };

  // Composer listeners (attach button, drop zone, paste) are rebound whenever
  // the composer is re-rendered; this releases the previous set.
  let teardownFileSources = null;
  let teardownEmoji = null;

  /* ------------------------------------------------------------ structure */

  const ui = {
    numberSelect: el("select.filter__select", { onchange: onNumberFilterChange }),
    search: el("input.filter__search", {
      type: "search",
      placeholder: "Search by name or number",
      oninput: debounce((event) => {
        state.search = event.target.value.trim();
        loadConversations();
      }),
    }),
    list: el("ul.convs"),
    listStatus: el("div.convs__status"),
    threadHeader: el("header.thread__header"),
    messages: el("div.thread__messages"),
    composer: el("footer.thread__composer"),
    connection: el("div.connbar", { hidden: true }),
  };

  // Mount points for the companion modules (search, reminders, reply buttons).
  // They own what goes inside; this file only guarantees the slots exist, keep
  // their id, and take no space while empty.
  const slots = {
    search: el("div.slot", { id: "wa-search-slot" }),
    topbar: el("div.slot", { id: "wa-topbar-slot" }),
    composer: el("div.slot", { id: "wa-composer-slot" }),
  };

  const layout = el("div.app", {}, [
    el("aside.sidebar", {}, [
      el("div.sidebar__top", {}, [
        el("div.sidebar__title", {}, ["WhatsApp"]),
        slots.search,
        me.is_wa_admin
          ? el("button.btn.btn--ghost.btn--sm", { onclick: openNumbers, type: "button", title: "Number names and agents" }, [
              icon("hash", { size: 15 }),
              "Numbers",
            ])
          : null,
        el("button.btn.btn--primary.btn--sm", { onclick: openNewContact, type: "button", title: "New contact" }, [
          icon("plus", { size: 15 }),
          "New",
        ]),
      ]),
      el("div.filter", {}, [ui.numberSelect, ui.search]),
      // List and status share one scroll box so the empty-state message sits
      // right under the (possibly empty) list instead of at the sidebar's foot.
      el("div.convs__wrap", {}, [ui.list, ui.listStatus]),
    ]),
    el("section.thread", {}, [ui.connection, ui.threadHeader, ui.messages, ui.composer]),
  ]);

  renderEmptyThread();

  /* ------------------------------------------------------------- loading */

  /**
   * Builds the inbox off-screen and only swaps it in once the first fetches
   * succeed — if they don't, the caller's boot screen is still mounted and can
   * show the error instead of an empty panel.
   */
  async function boot() {
    // /api/auth/me/ already carries the visible numbers, so the panel opens on
    // one round trip; the catalog call is only the fallback.
    state.numbers = asList(me.numbers, "numbers");
    if (!state.numbers.length) state.numbers = asList(await catalog.numbers(), "numbers");
    renderNumberFilter();
    await loadConversations();

    root.className = "";
    clear(root).append(layout);
    connectSocket();
    publishApi();

    // The frame's height is Bitrix's to decide, and the panel simply fills it.
    // Asking for a taller frame (there is no API for "how much room do I have")
    // meant guessing, and a guess that overshot pushed the portal page into a
    // scrollbar that hid its own header — worse than a shorter panel.
  }

  async function loadConversations({ keepActive = true } = {}) {
    ui.listStatus.textContent = "Loading…";
    try {
      const payload = await inbox.conversations({
        number: state.numberFilter || undefined,
        q: state.search || undefined,
        limit: PAGE_SIZE,
      });
      state.conversations = asList(payload, "conversations");
      renderConversations();
      ui.listStatus.textContent = state.conversations.length ? "" : "No conversations.";

      if (keepActive && state.activeId) {
        const still = state.conversations.some((c) => c.id === state.activeId);
        if (!still) renderEmptyThread();
      }
    } catch (error) {
      ui.listStatus.textContent = `Could not load the list: ${error.message}`;
      console.error("[a7-wa] conversations failed:", error);
    }
  }

  async function openConversation(id, { highlightMessageId } = {}) {
    if (state.loadingThread) return;
    state.activeId = id;
    state.loadingThread = true;
    renderConversations();
    clear(ui.messages).append(el("div.thread__hint", {}, ["Loading…"]));

    try {
      renderThreadHeader(findConversation(id));
      const payload = await inbox.messages(id, { limit: PAGE_SIZE });

      // The endpoint already hands back the newest slice in oldest-first order,
      // which is exactly the reading order — do not re-sort it.
      state.messages = asList(payload, "messages");

      // A search hit can point at a message far above the newest page.
      if (highlightMessageId) await loadUntilMessage(id, highlightMessageId);

      // It also returns the conversation, fresher than the list copy.
      const conversation = payload?.conversation || findConversation(id);
      if (payload?.conversation) upsertConversation(payload.conversation);

      // Captured before mark-read so the "new messages" divider survives.
      state.unreadAtOpen = conversation?.unread_count || 0;

      renderThreadHeader(conversation);
      renderMessages();
      renderComposer(conversation);

      if (highlightMessageId) highlightMessage(highlightMessageId);

      if (conversation?.unread_count) {
        inbox.markRead(id).then(() => {
          conversation.unread_count = 0;
          renderConversations();
        }, () => {});
      }
    } catch (error) {
      clear(ui.messages).append(el("div.thread__hint.thread__hint--error", {}, [`Could not load the thread: ${error.message}`]));
      console.error("[a7-wa] messages failed:", error);
    } finally {
      state.loadingThread = false;
    }
  }

  const findConversation = (id) => state.conversations.find((c) => c.id === id) || null;

  /** How far back a deep link may pull before giving up. */
  const HIGHLIGHT_MAX_PAGES = 5;

  /**
   * Pages backwards until the wanted message is loaded, so a deep link into an
   * old message lands on it instead of on an empty scroll position. Bounded:
   * a wrong id must not walk the whole history.
   */
  async function loadUntilMessage(conversationId, messageId) {
    const wanted = String(messageId);
    for (let page = 0; page < HIGHLIGHT_MAX_PAGES; page++) {
      if (state.messages.some((m) => String(m.id) === wanted)) return true;

      const oldest = state.messages[0]?.id;
      if (!oldest) return false;

      const older = asList(await inbox.messages(conversationId, { before: oldest, limit: PAGE_SIZE }), "messages");
      if (!older.length) return false;
      state.messages = [...older, ...state.messages];
    }
    return false;
  }

  /** Scrolls a message into view and flashes it, the way a search result should. */
  function highlightMessage(messageId) {
    const node = ui.messages.querySelector(`[data-id="${CSS.escape(String(messageId))}"]`);
    if (!node) return;
    node.scrollIntoView({ block: "center" });
    node.classList.add("msg--highlight");
    setTimeout(() => node.classList.remove("msg--highlight"), 2000);
  }

  /* ------------------------------------------------------------ rendering */

  function renderNumberFilter() {
    clear(ui.numberSelect);
    // With a single number the filter is noise — the agent has no choice to make.
    if (state.numbers.length < 2) {
      ui.numberSelect.hidden = true;
      return;
    }
    ui.numberSelect.hidden = false;
    ui.numberSelect.append(el("option", { value: "" }, ["Saare numbers"]));
    for (const number of state.numbers) {
      ui.numberSelect.append(el("option", { value: number.id }, [numberTitle(number)]));
    }
  }

  function onNumberFilterChange(event) {
    state.numberFilter = event.target.value;
    loadConversations({ keepActive: false });
  }

  /**
   * `title` is the server's own answer to "what should this number be called"
   * (admin label → gateway name → digits). Everything the agent sees goes
   * through it, so a rename shows up in one place.
   */
  const numberTitle = (number) => number?.title || number?.phone_number || "—";

  function renderConversations() {
    clear(ui.list);
    for (const conversation of state.conversations) {
      const open = conversation.is_session_open;
      ui.list.append(
        el(
          "li.conv",
          {
            class: [
              conversation.id === state.activeId ? "conv--active" : "",
              isClosingSoon(conversation) ? "conv--closing" : "",
            ]
              .filter(Boolean)
              .join(" "),
            onclick: () => openConversation(conversation.id),
          },
          [
            el("div.conv__avatar", {}, [initials(conversation.contact?.name || conversation.contact?.wa_id)]),
            el("div.conv__body", {}, [
              el("div.conv__line", {}, [
                el("span.conv__name", {}, [conversation.contact?.name || conversation.contact?.wa_id || "—"]),
                el("span.conv__time", {}, [stamp(conversation.last_message_at)]),
              ]),
              el("div.conv__line", {}, [
                el("span.conv__preview", {}, [
                  kindIcon(conversation.last_message_kind),
                  conversation.last_message_preview || "",
                ]),
                conversation.unread_count
                  ? el("span.badge", {}, [String(conversation.unread_count)])
                  : null,
              ]),
              el("div.conv__meta", {}, [
                el("span.dot", {
                  class: !open ? "dot--closed" : isClosingSoon(conversation) ? "dot--closing" : "dot--open",
                  title: !open
                    ? "Window closed"
                    : isClosingSoon(conversation)
                      ? `Window closing — ${untilText(conversation.session_expires_at) || "1 hour"} left`
                      : "Window open",
                }),
                el("span.conv__number", {}, [numberTitle(numberById(conversation.number_id))]),
              ]),
            ]),
          ]
        )
      );
    }
  }

  const numberById = (id) => state.numbers.find((n) => String(n.id) === String(id));

  /** Marks a media preview in the list; plain text and templates get no icon. */
  const kindIcon = (kind) => iconForKind(kind, { size: 13, className: "conv__kind" });

  /**
   * The slot anchors must be in the document from mount, not only while a chat
   * is open: the companion modules look them up once on wa:ready. Every render
   * path that clears the header or composer puts them back.
   */
  function renderEmptyThread() {
    clear(ui.threadHeader).append(slots.topbar);
    clear(ui.composer).append(slots.composer);
    clear(ui.messages).append(el("div.thread__hint", {}, ["Select a chat from the left."]));
  }

  function renderThreadHeader(conversation) {
    clear(ui.threadHeader);
    if (!conversation) {
      ui.threadHeader.append(slots.topbar);
      return;
    }

    const open = conversation.is_session_open;
    const left = untilText(conversation.session_expires_at);

    ui.threadHeader.append(
      el("div.thread__who", {}, [
        el("div.conv__avatar", {}, [initials(conversation.contact?.name || conversation.contact?.wa_id)]),
        el("div", {}, [
          el("div.thread__name", {}, [conversation.contact?.name || conversation.contact?.wa_id || "—"]),
          el("div.thread__sub", {}, [
            conversation.contact?.wa_id || "",
            " · ",
            numberTitle(numberById(conversation.number_id)),
          ]),
        ]),
      ]),
      el("div.thread__tools", {}, [
        el("span.pill", { class: sessionPillClass(conversation) }, [
          open ? (left ? `Window open · ${left}` : "Window open") : "Window closed",
        ]),
        conversation.assigned_agent
          ? el("span.pill", {}, [`@${conversation.assigned_agent.display_name || conversation.assigned_agent}`])
          : null,
        slots.topbar,
        state.me.is_wa_admin
          ? el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: () => openTransfer(conversation) }, [
              icon("users", { size: 15 }),
              "Transfer",
            ])
          : null,
      ])
    );
  }

  /** Within this many pixels of the end counts as "watching the live edge". */
  const STICK_THRESHOLD = 80;

  const isAtBottom = () =>
    ui.messages.scrollHeight - ui.messages.scrollTop - ui.messages.clientHeight <= STICK_THRESHOLD;

  const scrollToBottom = () => {
    ui.messages.scrollTop = ui.messages.scrollHeight;
  };

  // Images and videos have no height until they load, so the scroll that runs
  // right after render lands short and the newest bubble hides behind the
  // composer. Re-pin whenever a media element settles, unless the agent has
  // meanwhile scrolled up to read something.
  let followTail = true;
  ui.messages.addEventListener("scroll", () => {
    followTail = isAtBottom();
  });
  ui.messages.addEventListener(
    "load",
    () => {
      if (followTail) scrollToBottom();
    },
    true // capture: load does not bubble
  );

  /**
   * Follows new messages only when the agent is already at the bottom. Yanking
   * the view down while they are reading older history is worse than missing a
   * bubble they can scroll to.
   */
  function appendMessageNode(node, { wasAtBottom = isAtBottom() } = {}) {
    ui.messages.append(node);
    if (wasAtBottom) scrollToBottom();
  }

  /** The server warns at this mark; the panel derives the same state itself. */
  const CLOSING_SOON_MINUTES = 60;

  /**
   * Whether this chat's free window is about to lapse.
   *
   * Derived from session_expires_at rather than remembered from the
   * session.closing event: the task behind that event runs every 15 minutes and
   * re-sends for the same chat, and a computed answer is inherently
   * de-duplicated — it is also right for chats loaded after the event fired.
   */
  function isClosingSoon(conversation) {
    if (!conversation?.is_session_open) return false;
    const left = minutesUntil(conversation.session_expires_at);
    return left !== null && left >= 0 && left <= CLOSING_SOON_MINUTES;
  }

  /**
   * The window closing is the deadline that costs money — once it lapses only
   * a paid template reopens the chat — so the pill warns before it happens
   * rather than only reporting that it already did.
   */
  function sessionPillClass(conversation) {
    if (!conversation.is_session_open) return "pill--closed";
    const left = minutesUntil(conversation.session_expires_at);
    if (left !== null && left <= 30) return "pill--urgent";
    if (left !== null && left <= 120) return "pill--soon";
    return "pill--open";
  }

  function renderMessages() {
    clear(ui.messages);

    const unreadFrom = firstUnreadIndex();
    let lastDay = null;

    state.messages.forEach((message, index) => {
      const day = dayKey(message.created_at);
      if (day && day !== lastDay) {
        ui.messages.append(el("div.daysep", {}, [el("span", {}, [dayLabel(message.created_at)])]));
        lastDay = day;
      }
      if (index === unreadFrom) {
        ui.messages.append(el("div.unreadsep", {}, [el("span", {}, ["New messages"])]));
      }
      ui.messages.append(messageBubble(message));
    });

    followTail = true;
    scrollToBottom();
  }

  /**
   * Index of the first message in the unread run, or -1.
   *
   * The count is taken when the thread is opened, before it is marked read —
   * otherwise the divider would vanish the instant the agent looked at it. It
   * counts inbound messages from the end, which is what the server counts too.
   */
  function firstUnreadIndex() {
    const unread = state.unreadAtOpen;
    if (!unread) return -1;

    let seen = 0;
    for (let i = state.messages.length - 1; i >= 0; i--) {
      if (state.messages[i].direction !== "in") continue;
      seen += 1;
      if (seen === unread) return i;
    }
    return -1;
  }

  function messageBubble(message) {
    const outbound = message.direction === "out";
    const tick = outbound ? STATUS_TICK[message.status] : null;
    const failure = [message.error_code, message.error_detail].filter(Boolean).join(" · ");
    // On a shared number the agent needs to see who replied, but their own name
    // on every one of their bubbles is noise.
    const author = outbound && message.sent_by && message.sent_by.id !== state.me.id ? message.sent_by.display_name : null;

    const media = mediaNode(message);

    return el("div.msg", { class: outbound ? "msg--out" : "msg--in", "data-id": message.id ?? "" }, [
      el("div.msg__bubble", {}, [
        media,
        message.body ? el("div.msg__text", {}, [message.body]) : null,
        // Reactions, locations, contact cards and anything else we do not draw
        // still arrived — an empty bubble reads as a broken panel, so say what
        // it was instead of showing nothing.
        !media && !message.body ? el("div.msg__unsupported", {}, [unsupportedLabel(message.kind)]) : null,
        failure ? el("div.msg__error", {}, [failure]) : null,
        retryButton(message),
        el("div.msg__foot", {}, [
          author ? el("span.msg__author", {}, [author]) : null,
          el("span", {}, [stamp(message.created_at)]),
          tick
            ? el("span.tick", { class: tick.className || "", title: failure || tick.label }, [
                icon(tick.name, { size: 15 }),
              ])
            : null,
        ]),
      ]),
      reactionsNode(message),
    ]);
  }

  /**
   * Reactions hang under their own bubble, WhatsApp-style — they are not
   * messages of their own. The payload maps sender wa_id → emoji, so the same
   * emoji from several people collapses into one chip with a count.
   *
   * There is no way to send one from here: the gateway rejects the `reaction`
   * type outright.
   */
  function reactionsNode(message) {
    const emojis = Object.values(message.reactions || {}).filter(Boolean);
    if (!emojis.length) return null;

    const counts = new Map();
    for (const emoji of emojis) counts.set(emoji, (counts.get(emoji) || 0) + 1);

    return el(
      "div.reactions",
      { title: `${emojis.length} reaction${emojis.length > 1 ? "s" : ""}` },
      [...counts].map(([emoji, count]) =>
        el("span.reaction", {}, [emoji, count > 1 ? el("span.reaction__n", {}, [String(count)]) : null])
      )
    );
  }

  /**
   * Attachments are downloaded from Meta by a background task, so a message can
   * arrive before its file does. The server pushes a message.status event once
   * the download settles, which re-renders this bubble — so the waiting state
   * needs no polling and no retry affordance.
   *
   * The panel is same-origin with the API and the media view is cookie
   * authenticated, so `src` works directly: no fetch, no blob, no header.
   */
  /**
   * "Send again" under a failed outbound message.
   *
   * Only text can be replayed from what the panel holds: a failed attachment's
   * media_id is not in the message payload, so that one has to be re-attached.
   */
  function retryButton(message) {
    if (message.status !== "failed" || message.direction !== "out") return null;
    if (message.kind !== "text" || !message.body) return null;

    return el(
      "button.msg__retry",
      {
        type: "button",
        onclick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          button.textContent = "Sending…";
          const conversation = findConversation(state.activeId);
          if (conversation) await sendText(conversation, message.body);
          button.remove();
        },
      },
      [icon("refresh", { size: 13 }), "Send again"]
    );
  }

  /** Opens the viewer on this image, with the rest of the thread's images loaded. */
  function openImage(message) {
    const images = imagesInThread(state.messages);
    const at = Math.max(0, images.findIndex((i) => String(i.id) === String(message.id)));
    openLightbox(images, at);
  }

  function mediaNode(message) {
    const kind = String(message.kind || "").toLowerCase();
    if (!["image", "audio", "video", "document", "sticker"].includes(kind)) return null;

    if (message.media_failed) {
      return el("div.msg__media-failed", {}, [icon("alert", { size: 15 }), "This attachment is unavailable"]);
    }

    if (!message.media_url) {
      // Outbound attachments are uploaded straight to the gateway and never
      // stored our side, so there is nothing to show back — saying it is still
      // downloading would be plainly wrong. Inbound is the real waiting case.
      if (message.direction === "out") {
        return el("div.msg__sent-media", {}, [
          iconForKind(kind, { size: 15 }) || icon("paperclip", { size: 15 }),
          `${SENT_MEDIA_LABEL[kind] || "File"} sent`,
        ]);
      }
      return el("div.msg__pending", {}, [el("span.spinner.spinner--sm"), "Downloading attachment…"]);
    }

    if (!message.media_ready) {
      return el("div.msg__pending", {}, [el("span.spinner.spinner--sm"), "Downloading attachment…"]);
    }

    if (kind === "image" || kind === "sticker") {
      return el("img.msg__image", {
        src: message.media_url,
        alt: message.media_name || "image",
        loading: "lazy",
        title: "View full size",
        onclick: () => openImage(message),
      });
    }
    // Voice notes arrive as audio/ogg; a plain player is what they need.
    if (kind === "audio") return el("audio.msg__audio", { src: message.media_url, controls: true });

    if (kind === "video") {
      // No poster comes from the API, so preload the metadata — the browser
      // then paints the first frame instead of a black rectangle.
      return el("video.msg__video", { src: message.media_url, controls: true, preload: "metadata" });
    }

    return el("a.msg__doc", { href: message.media_url, target: "_blank", rel: "noopener", download: message.media_name || "" }, [
      el("div.msg__doc-icon", {}, [icon("file", { size: 22 })]),
      el("div.msg__doc-meta", {}, [
        el("div.msg__doc-name", { title: message.media_name || "" }, [message.media_name || "Document"]),
        el("div.msg__doc-sub", {}, [docSubtitle(message)]),
      ]),
      el("div.msg__doc-dl", { title: "Download" }, [icon("download", { size: 17 })]),
    ]);
  }

  const SENT_MEDIA_LABEL = { image: "Photo", sticker: "Sticker", video: "Video", audio: "Audio", document: "Document" };

  const UNSUPPORTED_LABEL = {
    location: "Location sent",
    contacts: "Contact card sent",
    reaction: "Reaction",
    interactive: "Interactive message",
    button: "Button reply",
    system: "System message",
  };

  const unsupportedLabel = (kind) =>
    UNSUPPORTED_LABEL[String(kind || "").toLowerCase()] || `[${kind || "unknown"}]`;

  function docSubtitle(message) {
    const ext = String(message.media_name || "").split(".").pop()?.toUpperCase();
    const size = formatBytes(message.media_size);
    return [ext && ext.length <= 5 ? ext : null, size].filter(Boolean).join(" · ") || "Download";
  }

  /* ------------------------------------------------------------- composer */

  function renderComposer(conversation) {
    teardownFileSources?.();
    teardownFileSources = null;
    teardownEmoji?.destroy();
    teardownEmoji = null;
    clear(ui.composer);
    if (!conversation) {
      ui.composer.append(slots.composer);
      return;
    }

    if (!conversation.is_session_open) {
      ui.composer.append(
        el("div.locked", {}, [
          el("div.locked__text", {}, [
            "The 24-hour window is closed, so a free-form message cannot be sent. Sending a template reopens it.",
          ]),
          slots.composer,
          el("button.btn.btn--primary", { type: "button", onclick: () => openTemplates(conversation) }, [
            "Choose a template",
          ]),
        ])
      );
      return;
    }

    const textarea = el("textarea.composer__input", {
      rows: 1,
      placeholder: "Write a message…",
      onkeydown: (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          submit();
        }
      },
      oninput: () => autoGrow(textarea),
    });

    async function submit() {
      const body = textarea.value.trim();
      if (!body) return;
      textarea.value = "";
      autoGrow(textarea);
      await sendText(conversation, body);
    }

    // Last cheap chance to reply: after the window lapses every message costs a
    // template, and Meta's marketing cap can refuse it outright.
    if (isClosingSoon(conversation)) {
      const left = untilText(conversation.session_expires_at);
      ui.composer.append(
        el("div.closingbar", {}, [
          icon("clock", { size: 15 }),
          el("span", {}, [
            `The window closes ${left ? `in ${left}` : "in under an hour"} — reply now, or a template will be needed.`,
          ]),
        ])
      );
    }

    const attachBtn = el("button.btn.btn--icon", { type: "button", title: "Attach" }, [icon("paperclip", { size: 19 })]);
    const emojiBtn = el("button.btn.btn--icon", { type: "button", title: "Emoji" }, [icon("smile", { size: 19 })]);

    ui.composer.append(
      el("div.composer", {}, [
        el("div.composer__attach", {}, [attachBtn]),
        el("div.composer__attach", {}, [emojiBtn]),
        slots.composer,
        textarea,
        el("button.btn.btn--primary.btn--send", { type: "button", onclick: submit, title: "Send" }, [
          icon("send", { size: 17 }),
          el("span.btn__text", {}, ["Send"]),
        ]),
      ])
    );

    teardownEmoji?.destroy();
    teardownEmoji = bindEmojiPicker({ button: emojiBtn, textarea });

    // Files can arrive from the button, a drop anywhere on the thread, or a
    // paste — a screenshot straight from the clipboard is the fastest of the
    // three and the one agents reach for most.
    teardownFileSources = bindFileSources({
      button: attachBtn,
      dropZone: ui.messages,
      pasteTarget: textarea,
      onFile: (file) => attachFile(conversation, file),
    });

    textarea.focus();
  }

  /** Grows the composer with the text, up to the CSS max-height. */
  function autoGrow(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }

  function attachFile(conversation, file) {
    const problem = checkFile(file);
    if (problem) {
      // Still open the dialog: it shows the reason next to the file, which is
      // clearer than a toast that disappears.
      openAttachmentDialog(file, { conversationId: conversation.id, onSent: () => {} });
      return;
    }
    openAttachmentDialog(file, {
      conversationId: conversation.id,
      onSent: (message) => {
        if (message?.id && !state.messages.some((m) => String(m.id) === String(message.id))) {
          state.messages.push(message);
          appendMessageNode(messageBubble(message), { wasAtBottom: true });
        }
      },
    });
  }

  /**
   * Optimistic append: the agent sees the bubble instantly, and the real message
   * (with its id and status) replaces it when the API answers. A failure turns
   * the same bubble red instead of losing what they typed.
   */
  function appendOptimistic(patch) {
    const draft = {
      id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      direction: "out",
      status: "queued",
      created_at: new Date().toISOString(),
      ...patch,
    };
    state.messages.push(draft);
    // The agent just hit send, so following their own message is always right.
    appendMessageNode(messageBubble(draft), { wasAtBottom: true });
    return draft;
  }

  function replaceMessage(draftId, real) {
    const index = state.messages.findIndex((m) => m.id === draftId);
    if (index === -1) return;
    const node = ui.messages.querySelector(`[data-id="${CSS.escape(String(draftId))}"]`);

    // The WebSocket echo of our own send can land before the HTTP response.
    // If it already painted the real message, drop the draft instead of
    // producing a second copy of it.
    const alreadyLive =
      real?.id !== undefined && state.messages.some((m, i) => i !== index && String(m.id) === String(real.id));
    if (alreadyLive) {
      state.messages.splice(index, 1);
      node?.remove();
      return;
    }

    state.messages[index] = { ...state.messages[index], ...real };
    node?.replaceWith(messageBubble(state.messages[index]));
  }

  async function sendText(conversation, body) {
    const draft = appendOptimistic({ kind: "text", body });
    try {
      const real = await inbox.send(conversation.id, { kind: "text", body });
      replaceMessage(draft.id, real || { status: "sent" });
    } catch (error) {
      replaceMessage(draft.id, { status: "failed", body: `${body}\n\n⚠ ${error.message}` });
    }
  }

  /* ------------------------------------------------------------- modals */

  async function templatesFor(numberId) {
    if (state.templates.has(numberId)) return state.templates.get(numberId);
    const list = asList(await catalog.templates(numberId), "templates");
    state.templates.set(numberId, list);
    return list;
  }

  /** Renders one input per {{n}} placeholder and returns a values getter. */
  function variableFields(template) {
    const count = Number(template?.variable_count) || 0;
    const inputs = [];
    const wrap = el("div.vars");
    for (let i = 1; i <= count; i++) {
      const input = el("input.field", { type: "text", placeholder: `{{${i}}}` });
      inputs.push(input);
      wrap.append(el("label.field__row", {}, [el("span", {}, [`Variable ${i}`]), input]));
    }
    return {
      node: wrap,
      values: () => Object.fromEntries(inputs.map((input, i) => [String(i + 1), input.value])),
      complete: () => inputs.every((input) => input.value.trim()),
    };
  }

  async function openTemplates(conversation) {
    const body = el("div.modal__body", {}, [el("div.thread__hint", {}, ["Loading templates…"])]);
    const dialog = modal("Approved templates", body, { wide: true });

    let templates;
    try {
      templates = await templatesFor(conversation.number_id);
    } catch (error) {
      clear(body).append(el("div.alert", {}, [`Could not load templates: ${error.message}`]));
      return;
    }

    if (!templates.length) {
      clear(body).append(el("div.thread__hint", {}, ["This number has no approved templates."]));
      return;
    }

    clear(body);
    const list = el("div.tpl-list");
    const detail = el("div.tpl-detail", {}, [el("div.thread__hint", {}, ["Choose a template."])]);
    body.append(el("div.tpl-split", {}, [list, detail]));

    for (const template of templates) {
      list.append(
        el("button.tpl", { type: "button", onclick: () => select(template) }, [
          el("div.tpl__name", {}, [template.name]),
          el("div.tpl__lang", {}, [template.language || ""]),
        ])
      );
    }

    function select(template) {
      const fields = variableFields(template);
      const send = el("button.btn.btn--primary", { type: "button" }, ["Send"]);
      send.addEventListener("click", async () => {
        if (!fields.complete()) {
          alert("Fill in every variable.");
          return;
        }
        send.disabled = true;
        send.textContent = "Sending…";
        try {
          await inbox.sendTemplate(conversation.id, {
            template_id: template.id,
            variables: fields.values(),
          });
          dialog.close();
          await openConversation(conversation.id);
        } catch (error) {
          send.disabled = false;
          send.textContent = "Send";
          alert(`The template was not sent: ${error.message}`);
        }
      });

      clear(detail).append(
        el("div.tpl-detail__preview", {}, [template.body_text || ""]),
        fields.node,
        el("div.modal__actions", {}, [send])
      );
    }
  }

  function openNumbers() {
    openNumbersAdmin({
      onSaved: (numbers) => {
        // A rename has to reach the list, the thread header and the filter,
        // all of which read from state.numbers.
        state.numbers = asList(numbers, "numbers");
        renderNumberFilter();
        renderConversations();
        const active = findConversation(state.activeId);
        if (active) renderThreadHeader(active);
      },
    });
  }

  function openNewContact() {
    const numberSelect = el(
      "select.field",
      {},
      state.numbers.map((number) => el("option", { value: number.id }, [numberTitle(number)]))
    );
    const phone = el("input.field", { type: "tel", placeholder: "971501234567" });
    const templateSelect = el("select.field", {}, [el("option", { value: "" }, ["Loading templates…"])]);
    const varsHost = el("div");
    const error = el("div.alert", { hidden: true });
    let fields = null;
    let templates = [];

    async function loadTemplates() {
      clear(templateSelect).append(el("option", { value: "" }, ["Loading templates…"]));
      clear(varsHost);
      try {
        templates = await templatesFor(numberSelect.value);
      } catch (err) {
        clear(templateSelect).append(el("option", { value: "" }, [`Load fail: ${err.message}`]));
        return;
      }
      clear(templateSelect).append(
        el("option", { value: "" }, [templates.length ? "Choose a template…" : "No approved templates"]),
        ...templates.map((t) => el("option", { value: t.id }, [`${t.name} (${t.language || ""})`]))
      );
    }

    templateSelect.addEventListener("change", () => {
      clear(varsHost);
      fields = null;
      const template = templates.find((t) => String(t.id) === templateSelect.value);
      if (!template) return;
      varsHost.append(el("div.tpl-detail__preview", {}, [template.body_text || ""]));
      fields = variableFields(template);
      varsHost.append(fields.node);
    });

    numberSelect.addEventListener("change", loadTemplates);

    const send = el("button.btn.btn--primary", { type: "button" }, ["Start a chat"]);
    const body = el("div.modal__body", {}, [
      el("label.field__row", {}, [el("span", {}, ["From which number"]), numberSelect]),
      el("label.field__row", {}, [el("span", {}, ["Customer's number"]), phone]),
      el("label.field__row", {}, [el("span", {}, ["Template"]), templateSelect]),
      varsHost,
      error,
      el("div.modal__actions", {}, [send]),
    ]);

    const dialog = modal("New Contact", body);
    loadTemplates();

    send.addEventListener("click", async () => {
      error.hidden = true;
      const to = phone.value.replace(/[^\d]/g, "");
      if (!to || !templateSelect.value) {
        error.hidden = false;
        error.textContent = "Both a number and a template are required.";
        return;
      }
      if (fields && !fields.complete()) {
        error.hidden = false;
        error.textContent = "Fill in every variable.";
        return;
      }
      send.disabled = true;
      send.textContent = "Sending…";
      try {
        const created = await inbox.start({
          number_id: numberSelect.value,
          to,
          template_id: templateSelect.value,
          variables: fields ? fields.values() : {},
        });
        dialog.close();
        await loadConversations({ keepActive: false });
        if (created?.id) await openConversation(created.id);
      } catch (err) {
        send.disabled = false;
        send.textContent = "Start a chat";
        error.hidden = false;
        error.textContent = err.message;
      }
    });
  }

  function openTransfer(conversation) {
    const agentId = el("input.field", { type: "text", placeholder: "Agent ID" });
    const reason = el("input.field", { type: "text", placeholder: "Wajah (optional)" });
    const error = el("div.alert", { hidden: true });
    const send = el("button.btn.btn--primary", { type: "button" }, ["Transfer"]);

    const dialog = modal(
      "Chat transfer",
      el("div.modal__body", {}, [
        el("p.modal__note", {}, ["The full history moves with the chat. Nothing is deleted."]),
        el("label.field__row", {}, [el("span", {}, ["New agent"]), agentId]),
        el("label.field__row", {}, [el("span", {}, ["Wajah"]), reason]),
        error,
        el("div.modal__actions", {}, [send]),
      ])
    );

    send.addEventListener("click", async () => {
      if (!agentId.value.trim()) {
        error.hidden = false;
        error.textContent = "An agent ID is required.";
        return;
      }
      send.disabled = true;
      try {
        await inbox.assign(conversation.id, { agent_id: agentId.value.trim(), reason: reason.value.trim() || undefined });
        dialog.close();
        await loadConversations();
      } catch (err) {
        send.disabled = false;
        error.hidden = false;
        error.textContent = err.message;
      }
    });
  }

  /* ------------------------------------------------- API for companions */

  /**
   * The seam the companion modules (search, reminders, reply buttons) build
   * against. They render into the #wa-*-slot anchors and drive the thread
   * through here, so they never reach into this file's internals.
   *
   * `wa:ready` fires last, once the panel is on screen and the API is callable.
   */
  function publishApi() {
    window.a7wa = window.a7wa || {};

    window.a7wa.openConversation = (id, options = {}) => openConversation(id, options);

    // Read-only views of what the panel is showing, so a companion does not
    // have to refetch what is already here.
    window.a7wa.getActiveConversationId = () => state.activeId;
    window.a7wa.getMe = () => state.me;

    window.dispatchEvent(new CustomEvent("wa:ready", { detail: { me: state.me } }));
  }

  /* ------------------------------------------------------------ realtime */

  function connectSocket() {
    const socket = new InboxSocket({
      onEvent: handleEvent,

      onStatus: ({ state: connState, resync }) => {
        state.connection = connState;
        ui.connection.hidden = connState === "open";
        ui.connection.textContent =
          connState === "open" ? "" : "Live connection lost — reconnecting…";
        // A gap in the socket means missed events; REST is the source of truth.
        if (connState === "open" && resync) {
          loadConversations();
          if (state.activeId) openConversation(state.activeId);
        }
      },

      // The socket was rejected as unauthenticated: the Django session lapsed.
      // Re-run the Bitrix handshake once, then reconnect — the agent never sees
      // a login prompt, which is the whole point of the SSO.
      onAuthLost: async () => {
        ui.connection.hidden = false;
        ui.connection.textContent = "Re-establishing your session…";
        try {
          await ensureSession();
          socket.connect();
          loadConversations();
        } catch (error) {
          ui.connection.textContent = `Your session could not be restored — reload the page. (${error.message})`;
          console.error("[a7-wa] re-auth failed:", error);
        }
      },
    });

    socket.connect();
    window.addEventListener("beforeunload", () => socket.close());
  }

  // Events carry whole objects, not ids, so the panel renders them directly
  // instead of refetching the list on every inbound message.
  function handleEvent(event, data) {
    if (event === "ready") return;
    if (event === "message.new") return onMessageNew(data);
    if (event === "message.status") return onMessageStatus(data.message);
    if (event === "conversation.updated" || event === "conversation.assigned") {
      return onConversationChanged(data.conversation);
    }
    // The closing warning carries the conversation, and the panel derives the
    // warning state from it — so re-sends of the same warning are harmless.
    if (event === "session.closing") return onConversationChanged(data.conversation);
    console.debug("[a7-wa] unhandled ws event:", event, data);
  }

  /** Inserts or replaces a conversation, keeping the list newest-activity-first. */
  function upsertConversation(conversation) {
    if (!conversation) return;
    // A filtered-out number must not silently reappear in the list.
    if (state.numberFilter && String(conversation.number_id) !== String(state.numberFilter)) return;

    const index = state.conversations.findIndex((c) => c.id === conversation.id);
    if (index === -1) state.conversations.unshift(conversation);
    else state.conversations[index] = conversation;

    state.conversations.sort(
      (a, b) => new Date(b.last_message_at || 0) - new Date(a.last_message_at || 0)
    );
    renderConversations();
    ui.listStatus.textContent = state.conversations.length ? "" : "No conversations.";
  }

  /**
   * Replaces a message already in the thread, in place.
   *
   * The server re-pushes the *same* message when something about it changes —
   * a reaction arriving or being taken back is the common case. Appending that
   * would show the message twice.
   *
   * @returns {boolean} false when the message is not in the open thread.
   */
  function replaceMessageById(message) {
    const index = state.messages.findIndex((m) => String(m.id) === String(message.id));
    if (index === -1) return false;

    state.messages[index] = message;
    const node = ui.messages.querySelector(`[data-id="${CSS.escape(String(message.id))}"]`);
    node?.replaceWith(messageBubble(message));
    return true;
  }

  function onMessageNew({ message, conversation }) {
    const active = conversation?.id === state.activeId;

    if (active) {
      // An id we already hold means this is a re-push (a reaction changed, or
      // the echo of a send we painted optimistically) — update, never append.
      if (!replaceMessageById(message)) {
        state.messages.push(message);
        appendMessageNode(messageBubble(message));
      }
      // An open thread is being read, so it must not accrue an unread badge.
      if (message.direction === "in") {
        inbox.markRead(state.activeId).catch(() => {});
        conversation.unread_count = 0;
      }
    }

    upsertConversation(conversation);
    if (active) {
      renderThreadHeader(conversation);
      renderComposer(conversation);
    }
  }

  function onMessageStatus(message) {
    if (!message || message.conversation_id !== state.activeId) return;
    replaceMessageById(message);
  }

  function onConversationChanged(conversation) {
    upsertConversation(conversation);
    if (conversation?.id === state.activeId) {
      // Assignment or an expiring window changes what the composer may do.
      renderThreadHeader(conversation);
      renderComposer(conversation);
    }
  }

  return boot();
}
