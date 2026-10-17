/**
 * The Lead AI screen: its own chat list on the left, the open chat on the right.
 *
 * "Chats" are the conversations a CRM campaign sent here with the popup's
 * "Lead AI" box ticked; they are not in the main inbox, and the Lead AI
 * assistant answers them. "Brokers" narrows them to the chats the assistant
 * labelled Broker (it stays silent there until someone presses Resume AI).
 * "Sara leads" is the list this screen always had (apps/leadbot): those chats
 * live in the main inbox, and their rows open there.
 *
 * The screen lies over the inbox, which keeps running underneath. While it is
 * open the inbox's panes are made inert: the inbox refocuses its own reply
 * box whenever its chat updates, and without this a reply typed here could
 * land in the inbox's chat and go to the wrong customer.
 *
 * "AI settings" in the bar opens the assistant's status and settings
 * (GET/PUT /api/leadai/settings/) for everyone; what may be changed there is
 * decided by the server, the dialog only hides what the agent cannot change.
 * "Shop media" opens the shops media library (shop-media.js) the same way, and
 * "Apartment photos" the studio and one-bedroom sets (unit-media.js, read only).
 *
 * The agent desk (desk.js, batch 2e): "Needs a person" and "Today" in the rail
 * are list views of the same chats (the server's order: the longest wait, the
 * start time), with their counts; Shops, Rent, Sale and Other beside Brokers
 * filter by track. An agent with Lead AI access sees every Lead AI chat here.
 */

import { el, clear, debounce, initials, stamp, toast } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { asList, inbox, leadAiApi } from "./api.js";
import { deskEmptyText, deskLine, deskParams, deskRail, isDeskTab, trackFilters } from "./desk.js";
import { closeShopMediaDialog, openShopMediaDialog } from "./shop-media.js";
import { closeUnitMediaDialog, unitMediaButton } from "./unit-media.js";
import { shopsForm, shopsValues } from "./shops.js";
import { residentialForm, residentialValues } from "./residential.js";
import { BROKER_LABEL, aiStateView, chatChips, contactName, isBrokerChat, momentLabel, mountThread, screenModal } from "./thread.js";

const PAGE = 40;
// The desk's wait times and counts are drawn again this often while the screen is open.
const DESK_TICK_MS = 60000;

/** The list's marker for an assistant that is not answering a chat. */
const ROW_MARK = { paused: "AI paused", stopped: "AI stopped", handed_over: "Handed over" };

/** The rail views that list Lead AI chats: all of them, or the desk's two. */
function isListTab(tab) {
  return tab === "chats" || isDeskTab(tab);
}

let screen = null;

export function isScreenOpen() {
  return screen !== null;
}

/** The conversation open in the screen right now, or null. */
export function openChatId() {
  return screen?.thread?.id ?? null;
}

/** Live events reach the screen through lead-ai.js, which hears every frame. */
export function deliverToScreen(event, data) {
  screen?.onEvent(event, data);
}

/** After a dropped socket: refetch what may have been missed. */
export function resyncScreen() {
  screen?.resync();
}

/** Closes the screen if it is open (an alert about a chat that lives in the main inbox). */
export function closeScreen() {
  screen?.close();
}

/**
 * @param {{ conversationId?: number, highlightMessageId?: number, me?: object, onUnreadChanged?: Function }} options
 */
export function openLeadAiScreen({ conversationId, highlightMessageId, me, onUnreadChanged } = {}) {
  if (screen) {
    if (conversationId) screen.select(conversationId, { highlightMessageId });
    return screen;
  }

  const state = {
    tab: "chats",
    rows: [],
    offset: 0,
    exhausted: false,
    q: "",
    brokers: false, // only the chats labelled Broker
    track: "", // the desk's track filter: "shop", "rent", "sale", "other" or none
    activeId: conversationId ? Number(conversationId) : null,
    pendingHighlight: highlightMessageId || null,
    thread: null,
    touchedInbox: false,
    loadSeq: 0,
  };
  // Listed chats waiting for a re-read of their Lead AI state, by id.
  const rowTimers = new Map();

  const listNode = el("div.lai-list");
  const statusNode = el("div.lai-list__status");
  const moreButton = el("button.lai-list__more", { type: "button", hidden: true, onclick: () => loadChats({ append: true }) }, [
    "Load more",
  ]);
  const search = el("input.lai-search", {
    type: "search",
    placeholder: "Search by name or number",
    autocomplete: "off",
    oninput: debounce(() => {
      if (screen !== self) return;
      state.q = search.value.trim();
      loadChats();
    }, 250),
  });
  const tabChats = railButton("chats", "messageSquare", "Chats");
  const tabSara = railButton("sara", "users", "Sara leads");
  // The agent desk (desk.js): Needs a person and Today, each a view of the chats; pressed again, back to Chats.
  const rail = deskRail({ onSelect: (tab) => setTab(state.tab === tab ? "chats" : tab) });
  const brokersButton = el("button.lai-filter", {
    type: "button",
    "aria-pressed": "false",
    title: "Only the chats the AI labelled Broker",
    onclick: () => {
      state.brokers = !state.brokers;
      brokersButton.setAttribute("aria-pressed", String(state.brokers));
      brokersButton.classList.toggle("is-on", state.brokers);
      loadChats();
    },
  }, ["Brokers"]);
  // The desk's track filters (?track=), one at a time.
  const tracks = trackFilters({
    onChange: (track) => {
      state.track = track;
      loadChats();
    },
  });
  const filters = el("div.lai-filters", {}, [brokersButton, ...tracks.buttons]);
  const main = el("main.lai-main");

  const root = el("section.lai-screen", { role: "dialog", "aria-label": "Lead AI" }, [
    el("div.lai-screen__glow", { "aria-hidden": "true" }),
    el("header.lai-bar", {}, [
      el("div.lai-bar__title", {}, [icon("smartphone", { size: 17 }), "Lead AI"]),
      el("div.lai-bar__note", {}, [
        "Chats from CRM campaigns sent with the Lead AI box. The AI assistant answers them; they stay here until you move one back.",
      ]),
      el("button.lai-btn.lai-btn--ghost.lai-bar__media", {
        type: "button",
        title: "The videos and photos the assistant sends for each shop type",
        onclick: () => openShopMediaDialog(),
      }, [icon("image", { size: 15 }), "Shop media"]),
      unitMediaButton(),
      el("button.lai-btn.lai-btn--ghost.lai-bar__settings", {
        type: "button",
        title: "The Lead AI assistant's status and settings",
        onclick: () => openSettingsDialog(),
      }, [icon("zap", { size: 15 }), "AI settings"]),
      el("button.lai-btn.lai-btn--icon.lai-bar__close", { type: "button", title: "Back to the inbox", onclick: () => close() }, [
        icon("close", { size: 18 }),
      ]),
    ]),
    el("div.lai-body", {}, [
      el("nav.lai-rail", { "aria-label": "Lead AI views" }, [tabChats, ...rail.buttons, tabSara]),
      el("aside.lai-side", {}, [
        search,
        filters,
        listNode,
        statusNode,
        moreButton,
      ]),
      main,
    ]),
  ]);

  const host = document.querySelector(".app") || document.body;
  // Everything else in the host goes inert while the screen is up (see top).
  // The alert stack stays clickable: an alert can open a chat from here.
  const madeInert = [...host.children].filter((node) => !node.inert && !node.classList?.contains("lai-alerts"));
  for (const node of madeInert) node.inert = true;
  host.append(root);
  document.addEventListener("keydown", onKey);
  document.addEventListener("visibilitychange", onVisible);
  // The desk's waits grow and today's list moves on with no event: drawn again, and its counts read again, every minute.
  const deskTimer = setInterval(() => {
    if (document.visibilityState !== "visible") return;
    if (isDeskTab(state.tab)) renderRows();
    rail.refresh();
  }, DESK_TICK_MS);
  // A desk view reads its list again shortly after a change that may move it (a handover, a booking, a reply).
  const reloadDeskSoon = debounce(() => {
    if (screen === self && isDeskTab(state.tab)) loadChats({ keep: true });
  }, 700);

  const self = {
    onEvent,
    select,
    close,
    resync,
    get thread() {
      return state.thread;
    },
  };
  screen = self;

  renderEmptyMain();
  setTab("chats");
  return self;

  /* --------------------------------------------------------------- shell */

  function onKey(event) {
    if (event.key !== "Escape" || event.isComposing) return;
    // A dialog or the image viewer opened from here takes its own Escape
    // (and marks it handled); the screen stays.
    if (event.defaultPrevented || document.querySelector(".modal, .lb")) return;
    // So does a box with text in it: closing would throw away a reply being
    // typed (the search box clears itself instead).
    if (event.target?.matches?.("textarea, input[type='search']") && event.target.value) return;
    close();
  }

  function onVisible() {
    // A socket gap means missed events; the list is refetched on return.
    if (document.visibilityState === "visible" && isListTab(state.tab)) loadChats({ keep: true });
  }

  function resync() {
    if (isListTab(state.tab)) loadChats({ keep: true });
    state.thread?.reload();
  }

  function close() {
    if (screen !== self) return;
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("visibilitychange", onVisible);
    clearInterval(deskTimer);
    rail.destroy();
    for (const timer of rowTimers.values()) clearTimeout(timer);
    rowTimers.clear();
    // Opened from this screen: it would stay over the inbox an alert opened.
    settingsDialog?.close();
    closeShopMediaDialog();
    closeUnitMediaDialog();
    state.thread?.destroy();
    state.thread = null;
    root.remove();
    for (const node of madeInert) node.inert = false;
    screen = null;
    // Reading a chat here goes through the inbox endpoints, which the AI desk
    // watches to know which chat is open. One small read of the inbox's own
    // chat points it back there, without touching that chat on screen.
    if (state.touchedInbox) {
      const id = window.a7wa?.getActiveConversationId?.();
      if (id) inbox.messages(id, { limit: 1 }).catch(() => {});
    }
  }

  function railButton(tab, glyph, label) {
    return el("button.lai-rail__btn", {
      type: "button",
      onclick: () => setTab(tab),
    }, [icon(glyph, { size: 16 }), el("span.lai-rail__label", {}, [label])]);
  }

  function setTab(tab) {
    const switched = state.tab !== tab;
    state.tab = tab;
    tabChats.classList.toggle("is-on", tab === "chats");
    tabSara.classList.toggle("is-on", tab === "sara");
    rail.active(tab);
    search.hidden = !isListTab(tab);
    filters.hidden = !isListTab(tab);
    // Another view's rows must not stand in for this one's while it loads.
    if (isListTab(tab)) loadChats({ keep: !switched });
    else loadSara();
  }

  function renderEmptyMain(text = "Select a chat from the left.") {
    state.thread?.destroy();
    state.thread = null;
    clear(main).append(el("div.lai-main__empty", {}, [icon("smartphone", { size: 28 }), text]));
  }

  /* --------------------------------------------------------------- chats */

  async function loadChats({ append = false, keep = false } = {}) {
    const seq = ++state.loadSeq;
    const offset = append ? state.offset : 0;
    if (!append && !keep) clear(listNode);
    statusNode.textContent = "Loading…";
    const tab = state.tab;
    try {
      const payload = await leadAiApi.chats({
        q: state.q,
        label: state.brokers ? BROKER_LABEL : "",
        ...deskParams(tab, state.track),
        limit: PAGE,
        offset,
      });
      // A newer load, another tab, or a closed screen wins over this answer.
      if (seq !== state.loadSeq || screen !== self || state.tab !== tab) return;
      const page = asList(payload, "results");
      state.rows = append ? mergeRows(state.rows, page) : page;
      state.offset = offset + page.length;
      state.exhausted = page.length < PAGE;
      // Only an unfiltered first page counts every unread Lead AI chat.
      if (!append && tab === "chats" && !state.q && !state.brokers && !state.track && typeof payload?.unread_chats === "number") {
        onUnreadChanged?.(payload.unread_chats);
      }
      if (payload?.desk_counts) rail.setCounts(payload.desk_counts);
      renderRows();
      if (state.activeId && !state.thread) openThread(state.activeId);
    } catch (error) {
      if (seq !== state.loadSeq || screen !== self) return;
      statusNode.textContent = `Could not load Lead AI chats: ${error.message}`;
    }
  }

  function mergeRows(existing, incoming) {
    const byId = new Map(existing.map((row) => [String(row.id), row]));
    for (const row of incoming) byId.set(String(row.id), row);
    return [...byId.values()];
  }

  function sortRows() {
    state.rows.sort((a, b) => {
      if (Boolean(b.is_pinned) !== Boolean(a.is_pinned)) return b.is_pinned ? 1 : -1;
      return (Date.parse(b.last_message_at || "") || 0) - (Date.parse(a.last_message_at || "") || 0);
    });
  }

  function renderRows() {
    if (!isListTab(state.tab)) return;
    // The desk's views keep the server's order: the longest wait, the start time.
    if (state.tab === "chats") sortRows();
    clear(listNode);
    // A row that lost its Broker label meanwhile leaves the Brokers list.
    const shown = state.brokers ? state.rows.filter(isBrokerChat) : state.rows;
    for (const row of shown) listNode.append(chatRow(row));
    statusNode.textContent = shown.length
      ? ""
      : state.q
        ? "No Lead AI chat matches that search."
        : isDeskTab(state.tab) || state.track
          ? deskEmptyText(state.tab, state.track)
          : state.brokers
            ? "No broker chats. The AI labels a chat Broker when the customer is a broker or asks for a client."
            : "No Lead AI chats yet. Tick the Lead AI box when you send a CRM campaign, and the replies come here.";
    moreButton.hidden = state.exhausted || !shown.length;
  }

  function chatRow(row) {
    const name = contactName(row);
    const unread = Number(row.unread_count || 0);
    const info = row.lead_ai_info || {};
    const chips = chatChips(row);
    return el("button.lai-row", {
      type: "button",
      class: [String(row.id) === String(state.activeId) ? "is-on" : "", unread ? "is-unread" : ""].filter(Boolean).join(" "),
      onclick: () => select(row.id),
    }, [
      el("div.lai-avatar", {}, [initials(name)]),
      el("div.lai-row__body", {}, [
        el("div.lai-row__top", {}, [
          el("span.lai-row__name", {}, [name]),
          el("span.lai-row__side", {}, [meetingMarker(row), el("span.lai-row__time", {}, [stamp(row.last_message_at)])]),
        ]),
        el("div.lai-row__preview", {}, [row.last_message_preview || "No messages yet"]),
        // Needs a person and Today: why the chat is there ("Handed over: asked for a call · waiting 25 min").
        isDeskTab(state.tab) ? deskLine(row) : null,
        el("div.lai-row__meta", {}, [
          aiMarker(row),
          row.number?.title || row.number?.phone_number ? el("span", {}, [row.number.title || `+${row.number.phone_number}`]) : null,
          info.campaign_name ? el("span.lai-row__campaign", {}, [info.campaign_name]) : null,
        ]),
        chips.length ? el("div.lai-row__chips", {}, chips) : null,
      ]),
      unread ? el("span.lai-badge", {}, [String(unread)]) : null,
    ]);
  }

  /** A clock beside the time when the assistant booked a meeting; "when" on hover. */
  function meetingMarker(row) {
    const appointment = row.lead_ai_appointment;
    if (!appointment || appointment.status !== "confirmed") return null;
    const text = appointment.when ? `Meeting: ${appointment.when}` : "Meeting booked";
    return el("span.lai-row__appt", { title: text }, [icon("clock", { size: 13 }), el("span.lai-sr", {}, [text])]);
  }

  /** "AI paused" / "AI stopped" / "Handed over" when the assistant is not answering. */
  function aiMarker(row) {
    const ai = row.lead_ai_ai;
    const label = ROW_MARK[ai?.mode];
    if (!label) return null;
    const view = aiStateView(ai, row);
    return el("span.lai-row__ai", { class: `lai-row__ai--${ai.mode}`, title: view ? `${view.label}. ${view.title}` : label }, [
      label,
    ]);
  }

  function select(id, { highlightMessageId: highlight } = {}) {
    // A row of Needs a person or Today opens where it is; from Sara leads, back to the chats.
    if (!isListTab(state.tab)) setTab("chats");
    if (String(state.activeId) === String(id) && state.thread) {
      if (highlight) state.thread.highlight(highlight);
      return;
    }
    state.activeId = Number(id);
    state.pendingHighlight = highlight || null;
    renderRows();
    openThread(state.activeId);
  }

  function openThread(id) {
    state.thread?.destroy();
    state.touchedInbox = true;
    const highlight = state.pendingHighlight;
    state.pendingHighlight = null;
    state.thread = mountThread(main, id, {
      me,
      highlightMessageId: highlight,
      onConversation: (conversation) => upsertRow(conversation, { quiet: true }),
      onMoved: (movedId) => removeRow(movedId, "The chat is back in the main inbox."),
    });
  }

  function upsertRow(conversation, { quiet = false } = {}) {
    if (!conversation?.id) return;
    const index = state.rows.findIndex((row) => String(row.id) === String(conversation.id));
    if (index === -1) {
      // The desk's views and a track filter are the server's lists: a chat joins them when they are read again.
      if (state.tab !== "chats" || state.track) return;
      state.rows.unshift(conversation);
    } else {
      // Keep the campaign details the list endpoint gave; live payloads lack them.
      state.rows[index] = { ...state.rows[index], ...conversation, lead_ai_info: state.rows[index].lead_ai_info };
    }
    if (!quiet || isListTab(state.tab)) renderRows();
  }

  function removeRow(id, note = "Select a chat from the left.") {
    state.rows = state.rows.filter((row) => String(row.id) !== String(id));
    if (String(state.activeId) === String(id)) {
      state.activeId = null;
      renderEmptyMain(note);
    }
    renderRows();
  }

  /**
   * A listed chat's assistant state or meeting changed: read its row again so
   * its markers follow. The open chat does this itself and hands the row up.
   */
  function refreshRowSoon(id) {
    const key = String(id);
    if (!state.rows.some((row) => String(row.id) === key)) return;
    clearTimeout(rowTimers.get(key));
    rowTimers.set(
      key,
      setTimeout(async () => {
        rowTimers.delete(key);
        try {
          const row = await leadAiApi.chat(key);
          if (screen !== self || !state.rows.some((item) => String(item.id) === key)) return;
          upsertRow(row);
        } catch {
          /* moved out of Lead AI: the plain event that says so takes the row away */
        }
      }, 400)
    );
  }

  /* ---------------------------------------------------------------- live */

  function onEvent(event, data) {
    const conversation = data?.conversation;
    const message = data?.message;
    // The assistant's own events and alerts carry flat ids, not objects.
    const id = conversation?.id ?? message?.conversation_id ?? data?.conversation_id;
    if (!id) return;

    if (!String(event).startsWith("leadai.")) {
      // A plain update that says the chat is no longer Lead AI: another agent
      // moved it back. Plain notices about a chat that still is (a reminder,
      // a transfer) leave it where it is.
      const movedBack =
        (event === "conversation.updated" || event === "message.new") && conversation && conversation.lead_ai === false;
      if (movedBack && state.rows.some((row) => String(row.id) === String(id))) {
        removeRow(id, "The chat is back in the main inbox.");
      }
      return;
    }

    if (String(state.activeId) === String(id)) state.thread?.onEvent(event, data);

    // "The AI is writing" concerns only the open chat.
    if (event === "leadai.ai.state") return;
    // A message, a handover, a booking or a take may move the desk's counts, and a desk view's own list.
    if (event === "leadai.message.new" || event === "leadai.ai.changed" || event === "leadai.alert" || String(event).startsWith("leadai.conversation.")) {
      rail.refresh();
      if (isDeskTab(state.tab)) reloadDeskSoon();
    }
    if (event === "leadai.ai.changed" || event === "leadai.alert") {
      if (String(state.activeId) !== String(id)) refreshRowSoon(id);
      return;
    }

    // A search, the Brokers or a track filter, or a desk view narrows the list; a chat that does not match it stays out.
    const narrowed = state.q || state.brokers || state.track || isDeskTab(state.tab);
    if (narrowed && !state.rows.some((row) => String(row.id) === String(id))) return;

    if (event === "leadai.message.new" && conversation) {
      const reading = String(state.activeId) === String(id) && document.visibilityState === "visible";
      upsertRow(reading ? { ...conversation, unread_count: 0 } : conversation);
      return;
    }
    if (conversation) upsertRow(conversation);
  }

  /* ---------------------------------------------------------- Sara leads */

  async function loadSara() {
    const seq = ++state.loadSeq;
    clear(listNode);
    moreButton.hidden = true;
    statusNode.textContent = "Loading…";
    try {
      const rows = asList(await leadAiApi.saraBoard(), "results");
      if (seq !== state.loadSeq || screen !== self || state.tab !== "sara") return;
      clear(listNode);
      for (const row of rows) listNode.append(saraRow(row));
      statusNode.textContent = rows.length
        ? ""
        : "No lead conversations yet. When a new lead is created in Bitrix, Sara starts here.";
    } catch (error) {
      if (seq !== state.loadSeq || screen !== self) return;
      statusNode.textContent = `Could not load Sara leads: ${error.message}`;
    }
  }

  function saraRow(row) {
    const openable = Boolean(row.conversation_id);
    return el("button.lai-row.lai-row--sara", {
      type: "button",
      disabled: !openable,
      title: openable ? "Opens in the main inbox" : "No chat yet",
      onclick: () => {
        if (!openable) return;
        // Sara's chats live in the main inbox, as they always have.
        close();
        window.a7wa?.openConversation?.(row.conversation_id);
      },
    }, [
      el("div.lai-avatar.lai-avatar--sara", {}, [initials(row.title || row.phone || "Lead")]),
      el("div.lai-row__body", {}, [
        el("div.lai-row__top", {}, [
          el("span.lai-row__name", {}, [row.title || row.phone || `Lead ${row.lead_id}`]),
          el("span.lai-state", { class: `lai-state--${row.kind || "pending"}` }, [row.badge || row.state]),
        ]),
        el("div.lai-row__meta", {}, [
          [row.phone, row.number ? `from ${row.number}` : "", row.agent].filter(Boolean).join(" · "),
        ]),
        row.error ? el("div.lai-row__error", {}, [row.error]) : null,
        row.reason && !row.error ? el("div.lai-row__meta", {}, [row.reason]) : null,
      ]),
    ]);
  }
}

/* ------------------------------------------------------------- AI settings */

// The reminder sweep runs every minute; older than this and reminders may be late.
const SWEEP_STALE_MS = 5 * 60 * 1000;
const NUMBER = new Intl.NumberFormat();

let settingsDialog = null;

function count(value) {
  const n = Number(value);
  return Number.isFinite(n) ? NUMBER.format(n) : "0";
}

function plural(n, one, many) {
  return n === 1 ? one : many;
}

/** The test numbers are private: an editor gets the list, anyone else only test_numbers_count. */
function testNumberCount(data) {
  if (Array.isArray(data.test_numbers)) return data.test_numbers.length;
  const n = Number(data.test_numbers_count);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** "3 min ago" for a moment within the hour, else the moment itself. */
function ago(iso) {
  const at = Date.parse(iso || "");
  if (!at) return "";
  const minutes = Math.round((Date.now() - at) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  return momentLabel(iso);
}

function section(title, ...children) {
  return el("section.lai-set__section", {}, [el("h3.lai-set__h", {}, [title]), ...children]);
}

/** Label / value pairs. A value is text or a node. */
function grid(rows) {
  return el(
    "dl.lai-set__grid",
    {},
    rows.flatMap(([label, value]) => [el("dt", {}, [label]), el("dd", {}, [value])])
  );
}

function warn(text) {
  return el("span.lai-set__warn", {}, [text]);
}

/** A link only for an https address; anything else is shown as text. */
function mapsLink(url) {
  const text = String(url || "").trim();
  if (!text) return "Not set";
  if (!/^https:\/\//i.test(text)) return text;
  return el("a.lai-set__link", { href: text, target: "_blank", rel: "noopener noreferrer" }, [text]);
}

function sweepNode(iso) {
  if (!iso) return warn("It has not run yet, so meeting reminders cannot go out.");
  const at = Date.parse(iso);
  const text = `Last ran ${ago(iso)}`;
  if (at && Date.now() - at > SWEEP_STALE_MS) {
    return warn(`${text}. It should run every minute, so meeting reminders may be late.`);
  }
  return text;
}

function statusSection(data) {
  const tests = testNumberCount(data);
  const rows = [
    [
      "Assistant",
      data.assistant_enabled
        ? el("span.lai-set__on", {}, ["On: it answers every Lead AI chat"])
        : tests
          ? `Off: it answers only the ${tests} test ${plural(tests, "number", "numbers")}`
          : "Off",
    ],
    ["OpenAI key", data.key_configured ? "Configured" : warn("Not set: the assistant cannot answer")],
    ["Model", data.model || "Not set"],
  ];
  if (data.paused_until) {
    const until = Date.parse(data.paused_until);
    rows.push([
      "Automatic pause",
      until && until > Date.now()
        ? warn(`Paused after repeated OpenAI errors until ${momentLabel(data.paused_until)}`)
        : `Ended ${momentLabel(data.paused_until)}`,
    ]);
  }
  rows.push(["Reminder sweep", sweepNode(data.last_sweep_at)]);
  if (data.hours) rows.push(["Office hours", data.hours]);
  if (data.updated_at) {
    rows.push(["Last change", `${momentLabel(data.updated_at)}${data.updated_by ? ` by ${data.updated_by}` : ""}`]);
  }
  return section("Status", grid(rows));
}

function usageSection(data) {
  const usage = data.usage_24h || {};
  const limit = Number(data.daily_call_limit) || 0;
  const tiles = [
    { label: "Replies", value: usage.replies },
    { label: "Failed", value: usage.failed, warn: Number(usage.failed) > 0 },
    { label: "Model calls", value: usage.calls, sub: limit ? `of ${count(limit)} a day` : "" },
    { label: "Prompt tokens", value: usage.prompt_tokens },
    { label: "Reply tokens", value: usage.completion_tokens },
  ];
  return section(
    "Last 24 hours",
    el(
      "div.lai-set__stats",
      {},
      tiles.map((tile) =>
        el("div.lai-set__stat", { class: tile.warn ? "lai-set__stat--warn" : "" }, [
          el("div.lai-set__stat-n", {}, [count(tile.value)]),
          el("div.lai-set__stat-l", {}, [tile.label]),
          tile.sub ? el("div.lai-set__stat-sub", {}, [tile.sub]) : null,
        ])
      )
    )
  );
}

function templateSection(numbers) {
  const list = numbers.map((number) => String(number ?? "").trim()).filter(Boolean);
  const title = "Meeting reminder template";
  if (!list.length) {
    return section(title, el("p.lai-set__p", {}, ["Every active number has the approved reminder template."]));
  }
  return section(
    title,
    el("p.lai-set__p.lai-set__warn", {}, [
      `${list.length} ${plural(list.length, "number has", "numbers have")} no approved reminder template. `,
      "There, a reminder cannot go out once the customer's 24-hour window has closed.",
    ]),
    el("details.lai-set__details", {}, [
      el("summary", {}, [list.length === 1 ? "Show the number" : `Show the ${list.length} numbers`]),
      el(
        "ul.lai-set__numbers",
        {},
        list.map((number) => el("li", {}, [/^\d+$/.test(number) ? `+${number}` : number]))
      ),
    ])
  );
}

/**
 * Who else gets the booking, handover and unanswered-message alerts:
 * "2311 (Matloob)", and an id no active agent has, so a typo shows.
 */
function alertRecipientsText(data) {
  const rows = Array.isArray(data.alert_recipients) ? data.alert_recipients : [];
  if (!rows.length) return "Nobody else";
  return rows
    .map((row) => {
      const id = String(row?.bitrix_user_id ?? "").trim();
      const name = String(row?.name ?? "").trim();
      return name ? `${id} (${name})` : `${id} (no active agent has this Bitrix id, so nobody is alerted)`;
    })
    .join(", ");
}

/**
 * Who has Lead AI access (the agent desk, Q37): they open every Lead AI chat
 * and get its alerts. Granted per agent in Agents & access.
 */
function deskAgentsText(data) {
  const names = (Array.isArray(data.desk_agents) ? data.desk_agents : [])
    .map((row) => String(row?.name ?? "").trim())
    .filter(Boolean);
  return names.length ? names.join(", ") : "Nobody yet (Agents & access, Lead AI)";
}

/** What the settings are, for an agent who cannot change them. */
function valuesSection(data) {
  const closed = data.closed_dates || [];
  const tests = testNumberCount(data);
  const pin = data.office_latitude && data.office_longitude ? `${data.office_latitude}, ${data.office_longitude}` : "Not set";
  return section(
    "Settings",
    grid([
      ["Office address", data.office_address || "Not set"],
      ["Google Maps link", mapsLink(data.office_maps_url)],
      ["Office pin", pin],
      ["Closed dates", closed.length ? closed.join(", ") : "None"],
      ["Test numbers", tests ? String(tests) : "None"],
      ["Daily call limit", count(data.daily_call_limit)],
      ["Also alerted", alertRecipientsText(data)],
      ["Lead AI access", deskAgentsText(data)],
    ])
  );
}

/** An admin who may not edit may still stop the assistant everywhere. */
function stopSection(data, onSaved) {
  const title = "Emergency stop";
  if (!data.assistant_enabled) {
    return section(title, el("p.lai-set__p", {}, ["The assistant is off. Only a panel admin can switch it on."]));
  }
  const note = el("p.lai-set__note", { role: "status" });
  const button = el("button.lai-btn.lai-btn--danger", {
    type: "button",
    onclick: async () => {
      button.disabled = true;
      note.textContent = "";
      note.classList.remove("lai-set__note--err");
      try {
        // Exactly this one key: the server lets a non-editor switch it off and nothing else.
        const next = await leadAiApi.saveSettings({ assistant_enabled: false });
        toast("The Lead AI assistant is switched off.");
        onSaved(next);
      } catch (error) {
        button.disabled = false;
        note.classList.add("lai-set__note--err");
        note.textContent = `Could not switch it off: ${error.message}`;
      }
    },
  }, [icon("pause", { size: 13 }), "Switch the AI off"]);
  return section(
    title,
    el("p.lai-set__p", {}, [
      "This stops the assistant in every Lead AI chat except the test numbers. Only a panel admin can switch it back on.",
    ]),
    el("div.lai-set__actions.lai-set__actions--start", {}, [button]),
    note
  );
}

/** The whole form, for a panel admin. Only the keys that changed are sent. */
function formSection(data, { onSaved, onClose }) {
  const fields = {};
  const note = el("p.lai-set__note", { role: "status" });

  function setNote(text, isError = false) {
    note.textContent = text;
    note.classList.toggle("lai-set__note--err", Boolean(text) && isError);
  }

  function field(key, label, hint, { type = "text", value = "", placeholder = "", inputmode = null, min = null, max = null, rows = 0, sharedHintId = "" } = {}) {
    const id = `lai-set-${key}`;
    const hintId = sharedHintId || (hint ? `${id}-hint` : "");
    // `rows` asks for a box that takes one entry per line.
    const input = rows
      ? el("textarea.lai-set__input", {
          id,
          rows,
          value,
          placeholder,
          autocomplete: "off",
          "aria-describedby": hintId || null,
        })
      : el("input.lai-set__input", {
          id,
          type,
          value,
          placeholder,
          autocomplete: "off",
          inputmode,
          min,
          max,
          "aria-describedby": hintId || null,
        });
    const error = el("div.lai-set__err", { id: `${id}-error`, hidden: true });
    input.addEventListener("input", () => clearError(key));
    fields[key] = { input, error, hintId };
    return el("div.lai-set__field", {}, [
      el("label.lai-set__label", { for: id }, [label]),
      input,
      hint && !sharedHintId ? el("div.lai-set__hint", { id: hintId }, [hint]) : null,
      error,
    ]);
  }

  function showError(key, message) {
    const item = fields[key];
    if (!item) return false;
    item.error.textContent = message;
    item.error.hidden = false;
    item.input.setAttribute("aria-invalid", "true");
    item.input.setAttribute("aria-describedby", [item.hintId, item.error.id].filter(Boolean).join(" "));
    return true;
  }

  function clearError(key) {
    const item = fields[key];
    if (!item || item.error.hidden) return;
    item.error.hidden = true;
    item.error.textContent = "";
    item.input.removeAttribute("aria-invalid");
    if (item.hintId) item.input.setAttribute("aria-describedby", item.hintId);
    else item.input.removeAttribute("aria-describedby");
  }

  const enabled = el("input.lai-toggle__input", {
    id: "lai-set-enabled",
    type: "checkbox",
    role: "switch",
    checked: Boolean(data.assistant_enabled),
    "aria-describedby": "lai-set-enabled-hint",
  });
  const enabledWarn = el("p.lai-set__p.lai-set__warn", { hidden: true, role: "status" });
  enabled.addEventListener("change", () => {
    const turningOn = enabled.checked && !data.assistant_enabled;
    const turningOff = !enabled.checked && data.assistant_enabled;
    enabledWarn.textContent = turningOn
      ? "When you save, the assistant answers every Lead AI chat, not only the test numbers."
      : turningOff
        ? "When you save, the assistant stops answering every chat except the test numbers."
        : "";
    enabledWarn.hidden = !(turningOn || turningOff);
  });

  const pinHintId = "lai-set-pin-hint";
  const save = el("button.lai-btn.lai-btn--primary", { type: "submit" }, ["Save"]);
  // The shops playbook's facts, brand and viewing agent (shops.js).
  const shopsPart = shopsForm(data);
  // The studios and one-bedrooms facts (residential.js).
  const residentialPart = residentialForm(data);

  const splitList = (text, pattern) =>
    String(text || "")
      .split(pattern)
      .map((item) => item.trim())
      .filter(Boolean);
  const sameList = (a, b) => a.length === b.length && a.every((item, index) => item === b[index]);

  function changes() {
    const out = {};
    if (enabled.checked !== Boolean(data.assistant_enabled)) out.assistant_enabled = enabled.checked;

    // Split on commas, semicolons and lines only, so "+971 50 123 4567" stays
    // one number. Each entry goes as typed: the server reads its digits, splits
    // an entry that holds several numbers, and names a bad one as it was typed.
    const numbers = splitList(fields.test_numbers.input.value, /[,;\n]+/);
    const digits = numbers.map((item) => item.replace(/\D/g, "")).filter(Boolean);
    if (!sameList(digits, (data.test_numbers || []).map(String))) out.test_numbers = numbers;

    const dates = splitList(fields.closed_dates.input.value, /[\s,;]+/);
    if (!sameList([...dates].sort(), (data.closed_dates || []).map(String).sort())) out.closed_dates = dates;

    const address = fields.office_address.input.value.replace(/\s+/g, " ").trim();
    if (address !== String(data.office_address || "")) out.office_address = address;

    const maps = fields.office_maps_url.input.value.trim();
    if (maps !== String(data.office_maps_url || "")) out.office_maps_url = maps;

    // The server reads the pin as a pair: one of them sent alone would clear the other.
    const lat = fields.office_latitude.input.value.trim();
    const lng = fields.office_longitude.input.value.trim();
    if (lat !== String(data.office_latitude || "") || lng !== String(data.office_longitude || "")) {
      out.office_latitude = lat;
      out.office_longitude = lng;
    }

    const limit = fields.daily_call_limit.input.value.trim();
    if (limit !== String(data.daily_call_limit ?? "")) out.daily_call_limit = limit;

    // Sent as typed: the server takes digits only, at most 10, and says which entry is wrong.
    const alertIds = splitList(fields.alert_bitrix_user_ids.input.value, /[\s,;]+/);
    if (!sameList(alertIds, (data.alert_bitrix_user_ids || []).map(String))) out.alert_bitrix_user_ids = alertIds;
    Object.assign(out, shopsPart.changes());
    Object.assign(out, residentialPart.changes());
    return out;
  }

  async function submit(event) {
    event.preventDefault();
    if (save.disabled) return;
    for (const key of Object.keys(fields)) clearError(key);
    shopsPart.clearErrors();
    residentialPart.clearErrors();
    setNote("");
    const payload = changes();
    if (!Object.keys(payload).length) {
      setNote("Nothing has changed.");
      return;
    }
    save.disabled = true;
    try {
      const next = await leadAiApi.saveSettings(payload);
      toast("Lead AI settings saved.");
      onSaved(next, payload);
    } catch (error) {
      save.disabled = false;
      const errors = error?.detail?.errors;
      let first = null;
      if (errors && typeof errors === "object") {
        for (const [key, message] of Object.entries(errors)) {
          if (showError(key, String(message))) {
            if (!first) first = fields[key].input;
            continue;
          }
          const input = shopsPart.showError(key, String(message)) || residentialPart.showError(key, String(message));
          if (input && !first) first = input;
        }
      }
      setNote(error?.message || "Could not save the settings.", true);
      first?.focus();
    }
  }

  const form = el("form.lai-set__form", { novalidate: true, onsubmit: submit }, [
    el("div.lai-set__field", {}, [
      el("label.lai-toggle", { for: "lai-set-enabled" }, [
        enabled,
        el("span.lai-toggle__track", { "aria-hidden": "true" }),
        el("span.lai-toggle__text", {}, ["The assistant answers Lead AI chats"]),
      ]),
      el("div.lai-set__hint", { id: "lai-set-enabled-hint" }, ["When it is off, it answers only the test numbers."]),
      enabledWarn,
    ]),
    field(
      "test_numbers",
      "Test numbers",
      "Customer numbers with country code, one per line or separated by commas or semicolons. Spaces inside a number " +
        "are fine (+971 50 999 0000). While the assistant is off, it still answers these.",
      { rows: 3, value: (data.test_numbers || []).join("\n"), placeholder: "971500000000\n+971 50 000 0001" }
    ),
    field(
      "closed_dates",
      "Closed dates",
      "Days the office is closed (public holidays) as YYYY-MM-DD, separated by commas. Sundays are always closed.",
      { value: (data.closed_dates || []).join(", "), placeholder: "2026-12-02, 2026-12-03" }
    ),
    field("office_address", "Office address", "The address the assistant gives customers.", {
      value: data.office_address || "",
    }),
    field("office_maps_url", "Google Maps link", "A link starting with https://. It goes out with every booking and reminder.", {
      type: "url",
      value: data.office_maps_url || "",
      placeholder: "https://maps.app.goo.gl/…",
    }),
    el("div.lai-set__pair", {}, [
      field("office_latitude", "Latitude", "", {
        value: data.office_latitude || "",
        inputmode: "decimal",
        placeholder: "25.000000",
        sharedHintId: pinHintId,
      }),
      field("office_longitude", "Longitude", "", {
        value: data.office_longitude || "",
        inputmode: "decimal",
        placeholder: "55.000000",
        sharedHintId: pinHintId,
      }),
    ]),
    el("div.lai-set__hint", { id: pinHintId }, [
      "The office pin, sent as a location after a booking. Leave both empty to send no pin.",
    ]),
    field(
      "daily_call_limit",
      "Daily call limit",
      "The most model calls the assistant may make in 24 hours, across all chats (0 to 20000).",
      { type: "number", value: String(data.daily_call_limit ?? ""), min: 0, max: 20000, inputmode: "numeric" }
    ),
    field(
      "alert_bitrix_user_ids",
      "Also alert (Bitrix user ids)",
      "Bitrix user ids separated by commas, at most 10. Besides the chat's owner, the CRM responsible and the agents " +
        "with Lead AI access, they get every booking, handover (a broker too) and unanswered-message alert, as a Bitrix " +
        "notification and, when they can open the chat, in this panel.",
      { value: (data.alert_bitrix_user_ids || []).join(", "), placeholder: "2311" }
    ),
    el("div.lai-set__hint", {}, [`Now: ${alertRecipientsText(data)}.`]),
    el("div.lai-set__hint", {}, [
      `Lead AI access (every Lead AI chat and its alerts, given in Agents & access): ${deskAgentsText(data)}.`,
    ]),
    shopsPart.node,
    residentialPart.node,
    note,
    el("div.lai-set__actions", {}, [
      el("button.lai-btn.lai-btn--ghost", { type: "button", onclick: () => onClose() }, ["Close"]),
      save,
    ]),
  ]);
  return section("Settings", form);
}

/**
 * The assistant's switch, status and settings. Everyone sees the status;
 * can_edit shows the form and can_disable alone an emergency "off". Those
 * flags only hide controls: the server checks every change itself.
 */
function openSettingsDialog() {
  if (settingsDialog) return;
  // Focus moves in; screenModal brings it back to the button that opened it.
  const body = el("div.lai-set", {}, [el("p.lai-set__note", {}, ["Loading…"])]);
  const dialog = screenModal("Lead AI settings", body, {
    wide: true,
    onClose: () => {
      if (settingsDialog === dialog) settingsDialog = null;
    },
  });
  dialog.box.classList.add("lai-modal--settings");
  settingsDialog = dialog;
  const keepFocusIn = () => {
    if (!dialog.box.contains(document.activeElement)) dialog.box.querySelector(".modal__x")?.focus();
  };
  keepFocusIn();

  leadAiApi.settings().then(
    (data) => {
      if (settingsDialog === dialog) render(data);
    },
    (error) => {
      if (settingsDialog !== dialog) return;
      clear(body).append(el("p.lai-set__note.lai-set__note--err", {}, [`Could not load the settings: ${error.message}`]));
    }
  );

  function saved(next, payload = {}) {
    if (settingsDialog !== dialog) return;
    render(next);
    keepFocusIn(); // the pressed button went with the old form
    // Who the assistant answers changed: the open list and chat read their state again.
    if ("assistant_enabled" in payload || "test_numbers" in payload) resyncScreen();
  }

  function render(data) {
    if (!data || typeof data !== "object") return;
    const parts = [statusSection(data)];
    if (data.usage_24h) parts.push(usageSection(data));
    if (Array.isArray(data.numbers_without_reminder_template)) {
      parts.push(templateSection(data.numbers_without_reminder_template));
    }
    if (data.can_edit) {
      parts.push(formSection(data, { onSaved: saved, onClose: () => dialog.close() }));
    } else {
      parts.push(valuesSection(data));
      if (data.shops_facts) parts.push(section("International City shops", shopsValues(data)));
      if (data.residential_facts) parts.push(section("International City — studios and one-bedrooms", residentialValues(data)));
      if (data.can_disable) parts.push(stopSection(data, (next) => saved(next, { assistant_enabled: false })));
      else parts.push(el("p.lai-set__note", {}, ["Only a panel admin can change these settings."]));
    }
    clear(body).append(...parts);
  }
}
