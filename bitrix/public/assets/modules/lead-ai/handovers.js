/**
 * "My handovers" — the handover desk (apps/leadai/handover_desk.py; Matloob 2026-10-22).
 *
 * The chats the AI handed to a person whose Bitrix responsible the signed-in agent is: the chat and the customer,
 * nothing else of the panel. The agent reads, replies inside the 24-hour window, sends a template from the chat's own
 * number, sees the viewing the chat booked, and says Done (the chat leaves the list; the AI carries on alone).
 *
 * The thread is thread.js's, scoped (no AI controls, no Move to inbox, no line on the team). The list is the server's
 * (/api/leadai/desk/mine/), read again on every live sign and every minute. An agent who holds no number has no inbox
 * layout and so no live socket: this screen opens one of its own (core/realtime.js re-broadcasts frames as "wa:event",
 * which lead-ai.js hands here).
 */

import { clear, debounce, el, stamp } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { InboxSocket } from "../../core/realtime.js";
import { asList, leadAiApi } from "./api.js";
import { contactName, mountThread } from "./thread.js";

const RELOAD_MS = 60000;
const EMPTY_TEXT = "No chat has been handed to you yet. When the AI hands a customer to you, the chat appears here and you get an alert.";

let screen = null;

export function isHandoversOpen() {
  return screen !== null;
}

export function deliverToHandovers(event, data) {
  screen?.onEvent(event, data);
}

export function closeHandovers() {
  screen?.close();
}

export function openHandoversScreen({ me, conversationId } = {}) {
  if (screen) {
    if (conversationId) screen.select(conversationId);
    return screen;
  }
  const state = {
    rows: [],
    activeId: conversationId ? Number(conversationId) : null,
    thread: null,
    loadSeq: 0,
    socket: null,
  };
  const listNode = el("div.lai-list");
  const statusNode = el("div.lai-list__status");
  const main = el("main.lai-main");
  const root = el("section.lai-screen.lai-screen--handovers", { role: "dialog", "aria-label": "My handovers" }, [
    el("div.lai-screen__glow", { "aria-hidden": "true" }),
    el("header.lai-bar", {}, [
      el("div.lai-bar__title", {}, [icon("messageSquare", { size: 17 }), "My handovers"]),
      el("div.lai-bar__note", {}, [
        "Chats the AI handed to you as the lead's responsible. Reply here or send a template; the AI stays quiet while you talk and carries on when you press Done.",
      ]),
      el("button.lai-btn.lai-btn--icon.lai-bar__close", { type: "button", title: "Close", onclick: () => close() }, [icon("close", { size: 18 })]),
    ]),
    el("div.lai-body.lai-body--handovers", {}, [el("aside.lai-side", {}, [listNode, statusNode]), main]),
  ]);

  const host = document.querySelector(".app") || document.body;
  // Everything else in the host goes inert while the screen is up; the alert stack stays clickable (lead-ai.js).
  const madeInert = [...host.children].filter((node) => !node.inert && !node.classList?.contains("lai-alerts"));
  for (const node of madeInert) node.inert = true;
  host.append(root);
  document.addEventListener("keydown", onKey);
  const timer = setInterval(() => {
    if (document.visibilityState === "visible") load({ keep: true });
  }, RELOAD_MS);
  // No inbox layout (an agent with no number): no live socket yet, so this screen opens its own.
  if (!document.querySelector(".sidebar__menu-btn")) {
    state.socket = new InboxSocket({
      onEvent: () => {},
      onStatus: ({ state: connState, resync }) => {
        if (connState === "open" && resync) load({ keep: true });
      },
    });
    state.socket.connect();
  }
  const reloadSoon = debounce(() => {
    if (screen === self) load({ keep: true });
  }, 700);

  const self = {
    onEvent,
    select,
    close,
    get thread() {
      return state.thread;
    },
  };
  screen = self;
  renderEmptyMain();
  load();
  return self;

  /* ------------------------------------------------------------- shell */

  function onKey(event) {
    if (event.key !== "Escape" || event.isComposing) return;
    if (event.defaultPrevented || document.querySelector(".modal, .lb")) return;
    if (event.target?.matches?.("textarea") && event.target.value) return;
    close();
  }

  function close() {
    state.thread?.destroy();
    state.thread = null;
    clearInterval(timer);
    document.removeEventListener("keydown", onKey);
    state.socket?.close();
    root.remove();
    for (const node of madeInert) node.inert = false;
    screen = null;
  }

  function renderEmptyMain(text = "Select a chat from the left.") {
    state.thread?.destroy();
    state.thread = null;
    clear(main).append(el("div.lai-main__empty", {}, [icon("messageSquare", { size: 28 }), text]));
  }

  /* -------------------------------------------------------------- list */

  async function load({ keep = false } = {}) {
    const seq = ++state.loadSeq;
    if (!keep) statusNode.textContent = "Loading…";
    try {
      const payload = await leadAiApi.deskMine();
      if (seq !== state.loadSeq || screen !== self) return;
      state.rows = asList(payload, "results");
      renderRows();
      if (state.activeId && !state.thread) openThread(state.activeId);
    } catch (error) {
      if (seq !== state.loadSeq || screen !== self) return;
      statusNode.textContent = `Could not load your handovers: ${error.message}`;
    }
  }

  function renderRows() {
    clear(listNode);
    if (!state.rows.length) {
      statusNode.textContent = EMPTY_TEXT;
      return;
    }
    statusNode.textContent = "";
    for (const row of state.rows) listNode.append(renderRow(row));
  }

  function renderRow(row) {
    const name = contactName(row);
    const unread = Number(row.unread_count || 0);
    const desk = row.desk || {};
    const line = [desk.reason_text || "Handed to you", desk.person_wrote ? "you replied" : waitWords(desk.waiting_minutes)].filter(Boolean).join(" · ");
    const appointment = row.appointment;
    const meetingText = appointment ? (appointment.when ? `Meeting: ${appointment.when}` : "Meeting booked") : "";
    return el("button.lai-row", {
      type: "button",
      class: [String(row.id) === String(state.activeId) ? "is-on" : "", unread ? "is-unread" : ""].filter(Boolean).join(" "),
      onclick: () => select(row.id),
    }, [
      el("div.lai-avatar", {}, [initials(name)]),
      el("div.lai-row__body", {}, [
        el("div.lai-row__top", {}, [
          el("span.lai-row__name", {}, [name]),
          el("span.lai-row__side", {}, [
            appointment ? el("span.lai-row__appt", { title: meetingText }, [icon("clock", { size: 13 })]) : null,
            el("span.lai-row__time", {}, [stamp(row.last_message_at)]),
          ]),
        ]),
        el("div.lai-row__preview", {}, [row.last_message_preview || "No messages yet"]),
        el("div.lai-row__meta.lai-hd-row__line", {}, [line]),
        meetingText ? el("div.lai-row__meta.lai-hd-row__meeting", {}, [meetingText]) : null,
      ]),
      unread ? el("span.lai-badge", {}, [String(unread)]) : null,
    ]);
  }

  function waitWords(minutes) {
    const m = Math.max(0, Number(minutes) || 0);
    if (m < 60) return `waiting ${m} min`;
    const h = Math.floor(m / 60);
    return h < 48 ? `waiting ${h} h` : `waiting ${Math.floor(h / 24)} days`;
  }

  function initials(name) {
    const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    return parts.slice(0, 2).map((word) => word[0].toUpperCase()).join("") || "?";
  }

  function select(id) {
    state.activeId = Number(id);
    renderRows();
    openThread(id);
  }

  function openThread(id) {
    state.thread?.destroy();
    state.thread = mountThread(main, Number(id), {
      me,
      scoped: true,
      onConversation: (conversation) => upsertRow(conversation),
      onDone: () => {
        state.rows = state.rows.filter((row) => String(row.id) !== String(id));
        state.activeId = null;
        renderRows();
        renderEmptyMain("Done. Pick another chat, or close.");
      },
      onMoved: () => {
        state.rows = state.rows.filter((row) => String(row.id) !== String(id));
        state.activeId = null;
        renderRows();
        renderEmptyMain();
      },
    });
  }

  function upsertRow(conversation) {
    if (!conversation?.id) return;
    const index = state.rows.findIndex((row) => String(row.id) === String(conversation.id));
    if (index === -1) return;
    const kept = state.rows[index];
    state.rows[index] = {
      ...kept,
      last_message_at: conversation.last_message_at ?? kept.last_message_at,
      last_message_preview: conversation.last_message_preview ?? kept.last_message_preview,
      unread_count: conversation.unread_count ?? kept.unread_count,
      is_session_open: conversation.is_session_open ?? kept.is_session_open,
    };
    renderRows();
  }

  /* -------------------------------------------------------------- live */

  function onEvent(event, data) {
    const conversation = data?.conversation;
    const message = data?.message;
    const id = conversation?.id ?? message?.conversation_id ?? data?.conversation_id;
    if (String(state.activeId) === String(id)) state.thread?.onEvent(event, data);
    if (event === "leadai.ai.state") return;
    const listed = state.rows.some((row) => String(row.id) === String(id));
    if (event === "leadai.message.new" && conversation && listed) {
      const reading = String(state.activeId) === String(id) && document.visibilityState === "visible";
      upsertRow(reading ? { ...conversation, unread_count: 0 } : conversation);
      return;
    }
    // A handover, a Done elsewhere, a booking, a move: the list is the server's, read again shortly.
    if (!listed || event === "leadai.alert" || event === "leadai.ai.changed" || String(event).startsWith("leadai.conversation.")) reloadSoon();
  }
}
