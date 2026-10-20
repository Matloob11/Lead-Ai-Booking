/**
 * One Lead AI chat: its messages, a reply box, "Move to inbox", and the
 * assistant's side of it (its state with Pause / Resume, the meeting it
 * booked, the line that says it is writing a reply).
 *
 * A fork of the main inbox's thread pane, not a reuse of it: that pane is a
 * closure inside inbox.js and cannot be mounted twice. It is built from the
 * same shared pieces (message media, special messages, attachments, the
 * template composer), so a message looks the same in both screens. Its classes
 * are its own (lai-), so the inbox's companion modules (reminders, reply
 * buttons, the AI desk button) never mistake it for the inbox's open chat.
 *
 * The assistant's state and the meeting come with the chat's row from
 * GET /api/leadai/chats/<id>/ (lead_ai_ai, lead_ai_appointment). They are
 * read again when the server says they changed (leadai.ai.changed), when an
 * alert names this chat, and when the meeting reminder goes out. An older
 * server sends nothing when a CRM sync finishes or a reminder comes due, so
 * the card also looks again a few times on its own while the chat is open.
 */

import { el, clear, dayKey, debounce, formatBytes, initials, modal, toast } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { mediaMessageNode } from "../../core/message-media.js";
import { specialMessageNode } from "../../core/message-special.js";
import { buttonReplyTag, templateButtonsRow, templateFooterNode } from "../../core/message-bubble-extras.js";
import { imagesInThread, openLightbox } from "../../core/lightbox.js";
import { numberNameWithDial } from "../../core/number-label.js";
import { bindFileSources, openAttachmentDialog } from "../attach.js";
import { openTemplateComposer } from "../template-composer.js";
import { asList, inbox, leadAiApi } from "./api.js";
import { callParts, trackChip } from "./desk.js";
import { followUpChip, followUpNote } from "./shops.js";

const PAGE_SIZE = 40;
const HIGHLIGHT_PAGES = 5;

/**
 * The keys of a chat row a re-read takes: the Lead AI ones, and the labels
 * (the assistant labels a broker's chat as it pauses itself).
 */
const LEAD_KEYS = ["lead_ai_info", "lead_ai_ai", "lead_ai_appointment", "labels"];

/** The inbox label the assistant puts on a broker's chat (engine.BROKER_LABEL), in any case. */
export const BROKER_LABEL = "Broker";
const BROKER_REASON = "broker_or_for_client";
const HEX_COLOUR = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const CHIP_LABELS_MAX = 3;

/** message.source of what the assistant itself sent. */
const AI_SOURCES = new Set(["leadai_ai", "leadai_tap"]);
const REMINDER_SOURCE = "leadai_reminder";
/** A shops chat's Template B, sent by the automatic follow-ups (followups.py). */
const FOLLOW_UP_SOURCE = "leadai_followup";

const THINKING_TEXT = "The AI is writing a reply… If you send first, it drops its reply.";
// The server always says "idle" when a turn ends; this only covers a lost frame.
const THINKING_MAX_MS = 90000;
// A finished CRM sync may send no live event (older servers): a card showing it pending looks again.
const CRM_RECHECK_MS = [20000, 60000, 180000];
// The sweep sends a due reminder within a minute or so; look a little after it.
const REMINDER_RECHECK_MS = 75000;
const RECHECK_HORIZON_MS = 12 * 3600 * 1000;

const TICKS = {
  queued: { name: "clock", label: "Queued" },
  sent: { name: "check", label: "Sent" },
  delivered: { name: "checkDouble", label: "Delivered" },
  read: { name: "checkDouble", label: "Read", className: "lai-tick--read" },
  failed: { name: "alert", label: "Failed", className: "lai-tick--failed" },
};

const KIND_LABEL = {
  location: "Location",
  contacts: "Contact card",
  reaction: "Reaction",
  interactive: "Interactive message",
  button: "Button reply",
  album: "Album",
  pinned_message: "Pinned message",
  sticker: "Sticker",
};

/** Why the assistant handed a chat to the team (LeadAiChatState.handover_reason). */
const HANDOVER_REASON = {
  customer_asked_human: "The customer asked to talk to a person",
  call_requested: "The customer asked for a call",
  price_or_details_insisted: "The customer insists on prices or details",
  complaint_or_upset: "The customer is upset or complaining",
  legal_visa_licence_contract: "A legal, visa, licence or contract question",
  broker_or_for_client: "A broker, or someone asking for a client",
  tenancy_issue: "A tenancy problem",
  renewal_terms: "A question about renewal rent or terms",
  media_received: "The customer sent a photo, document, contact or location",
  abroad_cannot_visit: "The customer is abroad or cannot visit",
  owner_viewing_slot: "The owner offered a viewing slot at their property",
  unclear: "The chat needs a person",
};

const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const DATE_FULL = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "long", year: "numeric" });
const DAY_TIME = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function timeOf(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : TIME.format(date);
}

/**
 * A moment in the browser's own time, like the rest of the panel: the time
 * alone today, day and time on any other day.
 */
export function momentLabel(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return dayKey(iso) === dayKey(new Date().toISOString()) ? TIME.format(date) : DAY_TIME.format(date);
}

/** English day separators (the shared dayLabel says "Aaj"/"Kal"). */
function dayLabel(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (dayKey(iso) === dayKey(new Date().toISOString())) return "Today";
  if (dayKey(iso) === dayKey(yesterday.toISOString())) return "Yesterday";
  return DATE_FULL.format(date);
}

export function contactName(conversation) {
  const contact = conversation?.contact || {};
  const waId = String(contact.wa_id || "");
  // A contact with no name is serialized with its number as the name.
  const name = [contact.name, contact.display_name, contact.profile_name].find((value) => value && String(value) !== waId);
  return name || (waId ? `+${waId}` : "Customer");
}

/** The chat carries the Broker label. */
export function isBrokerChat(conversation) {
  const wanted = BROKER_LABEL.toLowerCase();
  return (Array.isArray(conversation?.labels) ? conversation.labels : []).some(
    (label) => String(label?.name || "").trim().toLowerCase() === wanted
  );
}

/**
 * Small chips for a chat: its track on the shops script ("Rent · Studio",
 * "Shop", "Not known yet"; desk.js), or "IC shops" from a server that sends no
 * track, then its inbox labels (the first few). A label's own colour tints its
 * chip only when it is a plain hex colour.
 */
export function chatChips(conversation) {
  const chips = [];
  const track = trackChip(conversation);
  if (track) {
    chips.push(track);
  } else if (conversation?.lead_ai_info?.playbook === "ic_shops") {
    chips.push(
      el("span.lai-chip.lai-chip--playbook", { title: "The assistant follows the International City shops script in this chat" }, [
        "IC shops",
      ])
    );
  }
  const labels = (Array.isArray(conversation?.labels) ? conversation.labels : []).filter((label) => String(label?.name || "").trim());
  for (const label of labels.slice(0, CHIP_LABELS_MAX)) {
    const name = String(label.name).trim();
    const chip = el("span.lai-chip.lai-chip--label", { title: `Label: ${name}` }, [name]);
    const colour = String(label.colour || "").trim();
    if (HEX_COLOUR.test(colour)) chip.style.setProperty("--lai-chip", colour);
    chips.push(chip);
  }
  if (labels.length > CHIP_LABELS_MAX) {
    const rest = labels.slice(CHIP_LABELS_MAX).map((label) => String(label.name).trim());
    chips.push(el("span.lai-chip.lai-chip--more", { title: `Labels: ${rest.join(", ")}` }, [`+${rest.length}`]));
  }
  return chips;
}

/** Why the chat was handed over: the server's label (handover_label), else this screen's own map. */
function handoverText(ai) {
  // engine.HANDOVER_TEXT is written to follow a name ("asked for a call").
  const label = String(ai?.handover_label || "").trim().replace(/\.+$/, "");
  if (label) return /^[a-z]/.test(label) ? `The customer ${label}` : label;
  const key = String(ai?.handover_reason || "").trim();
  if (!key) return "The customer needs a person";
  return HANDOVER_REASON[key] || key.replace(/_/g, " ");
}

/**
 * The server's reason the assistant is not answering although its mode says
 * on ("Daily limit reached", "No Lead AI key"), as a sentence; "" when none.
 */
function aiNote(ai) {
  const text = String(ai?.note || "").trim();
  return text && !/[.!?]$/.test(text) ? `${text}.` : text;
}

/**
 * How the assistant's mode in one chat reads, for the pill in the thread
 * header and the marker on a list row. `ai` is a row's lead_ai_ai; null when
 * the row has none. The server's note, when it has one, ends the title.
 *
 * @returns {{label: string, tone: string, title: string} | null}
 */
export function aiStateView(ai, conversation = null) {
  const view = modeView(ai, conversation);
  const note = aiNote(ai);
  if (view && note) view.title = `${view.title} Not answering now: ${note}`;
  return view;
}

function modeView(ai, conversation) {
  const mode = String(ai?.mode || "");
  if (!mode) return null;
  const since = (iso) => (momentLabel(iso) ? ` since ${momentLabel(iso)}` : "");
  if (mode === "on") {
    const closed =
      conversation && conversation.is_session_open === false
        ? " The 24-hour window is closed, so it cannot write until the customer does."
        : "";
    return ai.test_number
      ? {
          label: "AI on (test number)",
          tone: "test",
          title: `The assistant is off for everyone else; this customer's number is a test number, so it answers here.${closed}`,
        }
      : { label: "AI on", tone: "on", title: `The Lead AI assistant answers this chat.${closed}` };
  }
  if (mode === "paused") {
    // Paused by nobody: the assistant stopped itself for a broker.
    if (!ai.paused_by && ai.handover_reason === BROKER_REASON) {
      return {
        label: "AI paused: broker",
        tone: "paused",
        title:
          `The customer is a broker or asks for a client, so the AI handed the chat to the team${since(ai.paused_at)}. ` +
          "It does not answer until someone presses Resume AI.",
      };
    }
    return {
      label: ai.paused_by ? `AI paused by ${ai.paused_by}` : "AI paused",
      tone: "paused",
      title: `Paused${since(ai.paused_at)}. The AI does not answer until someone presses Resume AI. Meeting reminders still go out.`,
    };
  }
  if (mode === "stopped") {
    return {
      label: ai.stop_reason ? `AI stopped: ${ai.stop_reason}` : "AI stopped",
      tone: "stopped",
      title: `Stopped${since(ai.stopped_at)}. The AI does not answer until someone presses Resume AI.`,
    };
  }
  if (mode === "handed_over") {
    return {
      label: "Handed to the team",
      tone: "handed",
      title:
        `Reason: ${handoverText(ai)}. The AI goes quiet here, handling only bookings and ` +
        "reminder taps, until someone from the team writes.",
    };
  }
  if (mode === "transferred") {
    return {
      label: "AI off (transferred)",
      tone: "off",
      title: "This chat was transferred to another agent, so the AI does not answer it.",
    };
  }
  // "Off" with a note is not the switch: it is on, but cannot answer anyone (no key).
  const title = aiNote(ai)
    ? "The Lead AI assistant cannot answer this chat."
    : "The Lead AI assistant is switched off. AI settings shows why.";
  return { label: "AI off", tone: "off", title };
}

/**
 * A dialog over the Lead AI screen, dark in every theme (lead-ai.css). The
 * shared modal leaves the screen behind it focusable: Tab reached the button
 * that opened it, and Enter there opened a second one. The screen is inert
 * while the dialog is up, and focus goes back to that button after.
 */
export function screenModal(title, content, { wide = false, onClose } = {}) {
  const opener = document.activeElement;
  const behind = document.querySelector(".lai-screen");
  const madeInert = Boolean(behind && !behind.inert);
  if (madeInert) behind.inert = true;
  let open = true;
  const dialog = modal(title, content, {
    wide,
    onClose: () => {
      if (!open) return;
      open = false;
      if (madeInert) behind.inert = false;
      onClose?.();
      if (opener?.isConnected && !opener.closest?.("[inert]")) opener.focus?.();
    },
  });
  dialog.box.classList.add("lai-modal");
  return dialog;
}

function failureText(message) {
  const code = String(message.error_code || "").trim();
  const detail = String(message.error_detail || "").trim();
  if (code === "131026") {
    return "131026 · Message undeliverable. This phone may not be on WhatsApp, or the country code is wrong.";
  }
  return [code, detail].filter(Boolean).join(" · ");
}

function fallbackLabel(message) {
  const kind = String(message.kind || "").toLowerCase();
  if (message.media_failed) return "Attachment was not saved on the server";
  if (message.status === "failed" || message.status === "exhausted") return failureText(message) || "Message failed to send";
  if (kind === "template") return message.template_name ? `Template: ${message.template_name}` : "Template message";
  return KIND_LABEL[kind] || "Message";
}

function crmWord(entity) {
  return { lead: "Lead", deal: "Deal", owner_data: "Owner Data" }[entity] || "CRM";
}

/** The reply buttons our meeting reminder carried: shown, never pressable here. */
function reminderChips(message) {
  const titles = (Array.isArray(message.buttons) ? message.buttons : [])
    .map((title) => String(title ?? "").trim())
    .filter(Boolean);
  if (!titles.length) return null;
  return el(
    "div.lai-msg__chips",
    { title: "The reply buttons sent with the reminder" },
    titles.map((title) => el("span.lai-msg__chip", {}, [icon("reply", { size: 11 }), title]))
  );
}

/** One line of the meeting card. */
function apptLine(iconName, text, { warn = false, muted = false, title = "" } = {}) {
  return el(
    "span.lai-appt__line",
    {
      class: [warn ? "lai-appt__line--warn" : "", muted ? "lai-appt__line--muted" : ""].filter(Boolean).join(" "),
      title: title || null,
    },
    [icon(iconName, { size: 12 }), el("span", {}, [text])]
  );
}

function reminderLine(appointment) {
  if (appointment.reminder_sent_at) {
    return apptLine("bell", `Reminder sent ${momentLabel(appointment.reminder_sent_at)}`);
  }
  if (appointment.reminder_error) return apptLine("alert", appointment.reminder_error, { warn: true });
  if (appointment.reminder_due_at) {
    return apptLine("bell", `Reminder at ${momentLabel(appointment.reminder_due_at)}`, {
      title: "The customer gets a WhatsApp reminder with reply buttons 30 minutes before the meeting.",
    });
  }
  if (appointment.status !== "confirmed") return null;
  return apptLine("bell", "No reminder planned", {
    muted: true,
    title: "No reminder is due for this meeting (booked less than 30 minutes ahead, or called off).",
  });
}

function crmLine(appointment) {
  if (appointment.crm_error) return apptLine("alert", `CRM: ${appointment.crm_error}`, { warn: true });
  if (appointment.crm_synced_at) {
    const moved = appointment.crm_stage_moved ? " The lead was moved to Meeting/Viewing Scheduled." : "";
    return apptLine("check", "Saved in CRM", { title: `Saved ${momentLabel(appointment.crm_synced_at)}.${moved}` });
  }
  return apptLine("clock", "Saving in CRM…", { muted: true });
}

/**
 * @param {HTMLElement} host  where the thread is drawn
 * @param {number} conversationId
 * @param {{ me?: object, onConversation?: Function, onMoved?: Function, highlightMessageId?: number }} hooks
 */
export function mountThread(host, conversationId, { me, onConversation, onMoved, highlightMessageId } = {}) {
  const state = {
    id: conversationId,
    conversation: null,
    messages: [],
    exhausted: false,
    loadingOlder: false,
    destroyed: false,
    sending: false,
    composerOpen: null, // the is_session_open the composer was built for
    input: null, // the reply box currently mounted
    lastDay: "",
    aiBusy: false, // a Pause / Resume request is on its way
  };
  const timers = { thinking: null, due: null, crm: null };
  let crmChecks = 0;
  let crmFor = null; // the meeting crmChecks counts for
  // Bumped by every answer that carries the chat's Lead AI state, so an older
  // re-read still on its way cannot draw over a newer one.
  let detailSeq = 0;
  // Bumped by every live sign that the AI started or stopped writing, so a
  // load that read the chat before it cannot undo it.
  let thinkingSeq = 0;
  let teardownFiles = null;
  // This chat's confirm dialogs: they go with it when another chat opens
  // (an alert can be clicked while one is up) or the screen closes.
  const dialogs = new Set();

  function chatModal(title, content) {
    const dialog = screenModal(title, content, { onClose: () => dialogs.delete(dialog) });
    dialogs.add(dialog);
    return dialog;
  }

  const header = el("div.lai-thread__head");
  const apptHost = el("div.lai-appt-host", { hidden: true });
  const list = el("div.lai-thread__messages", { onscroll: onScroll });
  const thinking = el("div.lai-thinking", { hidden: true, role: "status" }, [
    icon("zap", { size: 13 }),
    el("span.lai-thinking__text", {}, [THINKING_TEXT]),
  ]);
  const composer = el("div.lai-thread__composer");
  // The co-pilot's draft (lead_ai_ai.draft): what the AI would have said while a person has the chat.
  const draftHost = el("div.lai-thread__draft", { hidden: true });
  const root = el("section.lai-thread", {}, [header, apptHost, list, thinking, draftHost, composer]);
  clear(host).append(root);
  list.append(el("div.lai-thread__hint", {}, ["Loading…"]));

  const refreshSoon = debounce(() => refreshDetail(), 300);

  load({ highlight: highlightMessageId });

  async function load({ highlight } = {}) {
    const seq = ++detailSeq;
    const heard = thinkingSeq;
    try {
      // The messages, plus where the chat came from (campaign, CRM record),
      // the assistant's state and the open meeting.
      const [payload, detail] = await Promise.all([
        inbox.messages(state.id, { limit: PAGE_SIZE }),
        leadAiApi.chat(state.id).catch(() => null),
      ]);
      if (state.destroyed) return;
      state.messages = asList(payload, "messages");
      state.exhausted = state.messages.length < PAGE_SIZE;
      const conversation = payload?.conversation || null;
      if (conversation && detail) {
        for (const key of LEAD_KEYS) if (key in detail) conversation[key] = detail[key];
      }
      setConversation(conversation);
      // A reply already being written when the chat opened: its live
      // "thinking" went out before this chat listened. (Older servers do not
      // say; then only the live frames decide.)
      const ai = detail?.lead_ai_ai;
      if (ai && "thinking" in ai && heard === thinkingSeq) setThinking(ai.thinking === true);
      // A change announced while this was loading asked for a newer read
      // (dropped if it landed first, with nothing yet to merge into): read again.
      if (seq !== detailSeq) refreshSoon();
      if (highlight) await loadUntil(highlight);
      if (state.destroyed) return;
      renderMessages({ scroll: "bottom" });
      if (highlight) flash(highlight);
      markRead();
    } catch (error) {
      if (state.destroyed) return;
      clear(list).append(el("div.lai-thread__hint.lai-thread__hint--error", {}, [`Could not load the chat: ${error.message}`]));
    }
  }

  /** A search hit can sit above the newest page; fetch back a few pages for it. */
  async function loadUntil(messageId) {
    for (let page = 0; page < HIGHLIGHT_PAGES; page += 1) {
      if (state.messages.some((m) => String(m.id) === String(messageId)) || state.exhausted) return;
      const older = asList(await inbox.messages(state.id, { before: state.messages[0]?.id, limit: PAGE_SIZE }), "messages");
      if (state.destroyed) return;
      if (!older.length) {
        state.exhausted = true;
        return;
      }
      state.messages = [...older, ...state.messages];
      if (older.length < PAGE_SIZE) state.exhausted = true;
    }
  }

  function flash(messageId) {
    const node = list.querySelector(`[data-id="${CSS.escape(String(messageId))}"]`);
    if (!node) return;
    node.scrollIntoView({ block: "center" });
    node.classList.add("lai-msg--flash");
    setTimeout(() => node.classList.remove("lai-msg--flash"), 2200);
  }

  async function loadOlder() {
    if (state.loadingOlder || state.exhausted || !state.messages.length) return;
    state.loadingOlder = true;
    try {
      const older = asList(await inbox.messages(state.id, { before: state.messages[0].id, limit: PAGE_SIZE }), "messages");
      if (state.destroyed) return;
      if (!older.length) {
        state.exhausted = true;
      } else {
        state.messages = [...older, ...state.messages];
        if (older.length < PAGE_SIZE) state.exhausted = true;
      }
      renderMessages({ scroll: "preserve" });
    } catch (error) {
      toast(`Could not load earlier messages: ${error.message}`, "err");
    } finally {
      state.loadingOlder = false;
    }
  }

  function onScroll() {
    if (list.scrollTop < 60) loadOlder();
  }

  function setConversation(conversation) {
    if (!conversation) return;
    state.conversation = { ...(state.conversation || {}), ...conversation };
    renderHeader();
    renderAppointment();
    // Rebuilt only when what may be sent changes, so a reply being typed and
    // the cursor in it survive every live update.
    if (state.composerOpen !== Boolean(state.conversation.is_session_open)) renderComposer();
    renderDraft();
    onConversation?.(state.conversation);
  }

  /* ---------------------------------------------------------- co-pilot draft */

  /** The AI's draft reply for the agent: send it as it is, edit it in the reply box, ask the AI something, or drop it. */
  function renderDraft() {
    const ai = state.conversation?.lead_ai_ai;
    const draft = ai && ai.draft && typeof ai.draft === "object" ? ai.draft : null;
    if (!draft || !String(draft.text || "").trim()) {
      draftHost.hidden = true;
      clear(draftHost);
      return;
    }
    const text = String(draft.text);
    const asked = String(draft.question || "").trim();
    const kindTitle = draft.kind === "ordinary"
      ? "An ordinary question: if nobody sends or drops this draft, the AI sends it by itself after the minutes set in AI settings."
      : "A person's call: this draft never goes out by itself.";
    const head = el("div.lai-draft__head", {}, [
      icon("zap", { size: 13 }),
      el("span.lai-draft__title", { title: kindTitle }, [asked ? "AI answer to your question" : "AI draft reply"]),
      el("span.lai-draft__meta", {}, [since(draft.at).replace(/^ /, "") || "just now"]),
    ]);
    const body = el("div.lai-draft__body", {}, [
      asked ? el("div.lai-draft__question", {}, [`You asked: ${asked}`]) : null,
      el("div.lai-draft__text", {}, [text]),
    ]);
    const send = el("button.lai-btn.lai-btn--primary.lai-btn--sm", {
      type: "button",
      title: "Send these words to the customer from your name",
      onclick: () => sendDraft(text, send),
    }, [icon("send", { size: 13 }), "Send as me"]);
    const edit = el("button.lai-btn.lai-btn--ghost.lai-btn--sm", {
      type: "button",
      title: "Put the draft in the reply box to change it",
      onclick: () => editDraft(text),
    }, [icon("edit", { size: 13 }) || "✎", "Edit"]);
    const ask = el("button.lai-btn.lai-btn--ghost.lai-btn--sm", {
      type: "button",
      title: "Ask the AI a question about this chat, or for another reply",
      onclick: askAi,
    }, ["Ask AI"]);
    const drop = el("button.lai-btn.lai-btn--ghost.lai-btn--sm", {
      type: "button",
      title: "Drop this draft",
      onclick: () => dismissDraft(drop),
    }, ["Dismiss"]);
    clear(draftHost).append(el("div.lai-draft", { class: `lai-draft--${draft.kind === "ordinary" ? "ordinary" : "person"}` }, [
      head,
      body,
      el("div.lai-draft__actions", {}, [send, edit, ask, drop]),
    ]));
    draftHost.hidden = false;
  }

  async function sendDraft(text, button) {
    if (!state.input || !state.submit) {
      toast("The reply box is closed (the 24-hour window): send a template instead.", "err");
      return;
    }
    if (button) button.disabled = true;
    try {
      state.input.value = text;
      await state.submit();
      await leadAiApi.draftUsed(state.id, text);
      await refreshDetail();
    } catch (error) {
      toast(`Could not send the draft: ${error.message}`, "err");
      if (button) button.disabled = false;
    }
  }

  function editDraft(text) {
    if (!state.input) {
      toast("The reply box is closed (the 24-hour window): send a template instead.", "err");
      return;
    }
    state.input.value = text;
    state.input.style.height = "auto";
    state.input.style.height = `${Math.min(state.input.scrollHeight, 140)}px`;
    state.input.focus();
    state.draftEdited = text; // the composer's send then reports the edited words (draftUsed)
  }

  function askAi() {
    const input = el("textarea.lai-input.lai-ask__input", { rows: 3, placeholder: "e.g. Is the deposit refundable? / Write a reply about parking" });
    const go = el("button.lai-btn.lai-btn--primary", { type: "button" }, ["Ask"]);
    const cancel = el("button.lai-btn.lai-btn--ghost", { type: "button", onclick: () => dialog.close() }, ["Cancel"]);
    const dialog = chatModal("Ask AI about this chat", el("div.lai-ask", {}, [input, el("div.lai-confirm__actions", {}, [cancel, go])]));
    go.onclick = async () => {
      const question = input.value.trim();
      if (!question) return;
      go.disabled = true;
      try {
        await leadAiApi.draftAsk(state.id, question);
        dialog.close();
        toast("The AI is writing a draft; it appears above the reply box in a moment.");
      } catch (error) {
        go.disabled = false;
        toast(`Could not ask: ${error.message}`, "err");
      }
    };
    setTimeout(() => input.focus(), 0);
  }

  async function dismissDraft(button) {
    if (button) button.disabled = true;
    try {
      const row = await leadAiApi.draftDismiss(state.id);
      detailSeq += 1;
      applyLeadAi(row);
    } catch (error) {
      toast(`Could not drop the draft: ${error.message}`, "err");
      if (button) button.disabled = false;
    }
  }

  /** Takes only the Lead AI part of a chat row (a re-read, Pause, Resume, Cancel). */
  function applyLeadAi(row) {
    // Before the first load lands there is nothing to merge into; that load reads it anyway.
    if (!row || typeof row !== "object" || !state.conversation) return;
    const part = { id: state.id };
    for (const key of LEAD_KEYS) if (key in row) part[key] = row[key];
    setConversation(part);
  }

  async function refreshDetail() {
    if (state.destroyed) return;
    const seq = ++detailSeq;
    try {
      const detail = await leadAiApi.chat(state.id);
      if (state.destroyed || seq !== detailSeq) return;
      applyLeadAi(detail);
    } catch {
      /* moved out of Lead AI, or a blip: the next event or the next open reads it again */
    }
  }

  async function markRead() {
    if (!state.conversation?.unread_count || document.visibilityState !== "visible") return;
    try {
      await inbox.markRead(state.id);
      state.conversation = { ...state.conversation, unread_count: 0 };
      onConversation?.(state.conversation);
    } catch {
      /* the next open marks it */
    }
  }

  /* ------------------------------------------------------------ header */

  function renderHeader() {
    const conversation = state.conversation;
    if (!conversation) return;
    const name = contactName(conversation);
    const waId = conversation.contact?.wa_id ? `+${conversation.contact.wa_id}` : "";
    const lead = conversation.lead_ai_info || {};
    const crm = lead.crm_entity && lead.crm_id ? `${crmWord(lead.crm_entity)} #${lead.crm_id}` : "";
    const note = aiNote(conversation.lead_ai_ai);
    const meta = [
      waId !== name ? waId : "",
      conversation.number ? `on ${numberNameWithDial(conversation.number)}` : "",
      conversation.assigned_agent?.display_name ? `agent ${conversation.assigned_agent.display_name}` : "",
    ].filter(Boolean);
    // The shops assistant's "check back in a month" date, and a follow-up waiting for Meta, beside the chat's chips.
    const chips = [...chatChips(conversation), followUpChip(conversation), followUpNote(conversation)].filter(Boolean);

    clear(header).append(
      el("div.lai-avatar", {}, [initials(name)]),
      el("div.lai-thread__who", {}, [
        el("div.lai-thread__name", {}, [name]),
        el("div.lai-thread__meta", {}, [meta.join(" · ")]),
        chips.length ? el("div.lai-thread__chips", {}, chips) : null,
        lead.campaign_name || crm
          ? el("div.lai-thread__meta.lai-thread__meta--source", {}, [
              icon("send", { size: 12 }),
              [lead.campaign_name, crm].filter(Boolean).join(" · "),
            ])
          : null,
        // The pill can say "AI on" while the assistant is held back (an OpenAI pause, the daily limit).
        note ? el("div.lai-thread__meta.lai-thread__meta--ai", {}, [icon("zap", { size: 12 }), `AI not answering: ${note}`]) : null,
        // What the assistant remembers of this customer from chats on our other numbers (lead_ai_ai.memory, the detail).
        Array.isArray(conversation.lead_ai_ai?.memory) && conversation.lead_ai_ai.memory.length
          ? el("div.lai-thread__meta.lai-thread__meta--memory", { title: conversation.lead_ai_ai.memory.join("\n") }, [
              icon("clock", { size: 12 }),
              `Earlier chats: ${String(conversation.lead_ai_ai.memory[conversation.lead_ai_ai.memory.length - 1]).replace(/^- /, "")}`,
            ])
          : null,
      ]),
      el("div.lai-thread__tools", {}, [
        ...aiControls(conversation),
        el("span.lai-window", { class: conversation.is_session_open ? "is-open" : "is-closed" }, [
          conversation.is_session_open ? "24h window open" : "Window closed",
        ]),
        el("button.lai-btn.lai-btn--ghost.lai-move", {
          type: "button",
          title: "Put this chat back in the main inbox",
          onclick: confirmMove,
        }, [icon("reply", { size: 15 }), "Move to inbox"]),
      ])
    );
  }

  /** The assistant's pill, and Pause / Resume where they apply. */
  function aiControls(conversation) {
    const ai = conversation.lead_ai_ai;
    const view = aiStateView(ai, conversation);
    if (!view) return [];
    const nodes = [
      el("span.lai-ai", { class: `lai-ai--${view.tone}`, title: view.title }, [
        icon("zap", { size: 12 }),
        el("span.lai-ai__label", {}, [view.label]),
      ]),
    ];
    if (["paused", "stopped", "handed_over"].includes(ai.mode)) nodes.push(aiButton("resume"));
    if (["on", "handed_over"].includes(ai.mode)) nodes.push(aiButton("pause"));
    return nodes;
  }

  function aiButton(action) {
    const pause = action === "pause";
    return el("button.lai-btn.lai-btn--ghost.lai-btn--sm.lai-ai-btn", {
      type: "button",
      disabled: state.aiBusy,
      title: pause
        ? "Stop the AI answering this chat until someone resumes it. Meeting reminders still go out."
        : "Let the AI answer this chat again.",
      onclick: (event) => setAi(action, event.currentTarget),
    }, [icon(pause ? "pause" : "play", { size: 12 }), pause ? "Pause AI" : "Resume AI"]);
  }

  async function setAi(action, button) {
    if (state.aiBusy) return;
    state.aiBusy = true;
    if (button) button.disabled = true;
    const pause = action === "pause";
    let row = null;
    let failure = null;
    try {
      row = pause ? await leadAiApi.pauseAi(state.id) : await leadAiApi.resumeAi(state.id);
    } catch (error) {
      failure = error;
    }
    state.aiBusy = false;
    if (state.destroyed) return;
    // Drawn again either way: the pressed button was disabled by hand, and an
    // answer that is not a chat row redraws nothing below.
    renderHeader();
    if (failure) {
      toast(`Could not ${pause ? "pause" : "resume"} the AI: ${failure.message}`, "err");
      return;
    }
    detailSeq += 1;
    applyLeadAi(row);
    if (pause) {
      toast("The AI is paused in this chat.");
    } else if (row?.lead_ai_ai?.mode === "on") {
      toast("The AI answers this chat again.");
    } else {
      const view = aiStateView(row?.lead_ai_ai);
      toast(`Resumed. The AI still does not answer here (${view ? view.label : "AI off"}).`);
    }
  }

  function confirmMove() {
    const stay = el("button.lai-btn.lai-btn--ghost", { type: "button", onclick: () => dialog.close() }, ["Cancel"]);
    const actions = el("div.lai-confirm__actions", {}, [
      stay,
      el("button.lai-btn.lai-btn--primary", {
        type: "button",
        onclick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          try {
            await leadAiApi.moveToInbox(state.id);
            dialog.close();
            toast("Moved to the main inbox.");
            onMoved?.(state.id);
          } catch (error) {
            button.disabled = false;
            toast(`Could not move the chat: ${error.message}`, "err");
          }
        },
      }, ["Move to inbox"]),
    ]);
    const booked = Boolean(state.conversation?.lead_ai_appointment);
    const dialog = chatModal("Move to the main inbox?", el("div.lai-confirm", {}, [
      el("p", {}, [
        `${contactName(state.conversation)} will show in the main inbox again and leave Lead AI. `,
        "A later Lead AI campaign to this customer brings the chat back here.",
        booked ? " A booked meeting stays booked and is still reminded." : null,
      ]),
      actions,
    ]));
    // Focus moves in, on the safe answer.
    stay.focus();
  }

  /* ----------------------------------------------------- meeting card */

  function renderAppointment() {
    const appointment = state.conversation?.lead_ai_appointment || null;
    const stick = nearBottom();
    clear(apptHost);
    apptHost.hidden = !appointment;
    if (appointment) apptHost.append(appointmentCard(appointment));
    if (stick && state.messages.length) list.scrollTop = list.scrollHeight;
    planRechecks(appointment);
  }

  function appointmentCard(appointment) {
    const confirmed = appointment.status === "confirmed";
    const when = String(appointment.when || "").trim();
    const note = String(appointment.note || "").trim();
    const main = confirmed ? when || "Time not set" : note || when || "No time agreed yet";
    const lines = [];
    if (!confirmed && note && when) lines.push(apptLine("clock", `Time mentioned: ${when}`, { title: "Dubai time" }));
    // A call says so in its status ("Sales call") once the server names it.
    if (appointment.place && appointment.place !== "office" && !appointment.call_label) {
      lines.push(apptLine("mapPin", appointment.place_label || appointment.place));
    }
    if (appointment.customer_state) {
      lines.push(
        el("span.lai-appt__state", { class: `lai-appt__state--${appointment.customer_state}` }, [
          appointment.customer_state_label || appointment.customer_state,
        ])
      );
    }
    const reminder = reminderLine(appointment);
    if (reminder) lines.push(reminder);
    lines.push(crmLine(appointment));
    // A call (the agent desk, desk.js): "Sales call", I'll call until someone takes it, then who has it.
    const call = callParts(appointment, {
      me,
      take: () => leadAiApi.takeCall(state.id),
      onRow: (row) => {
        detailSeq += 1;
        applyLeadAi(row);
      },
      onStale: () => refreshDetail(),
      isGone: () => state.destroyed,
    });

    return el("div.lai-appt", { class: confirmed ? "lai-appt--confirmed" : "lai-appt--tentative" }, [
      el("div.lai-appt__icon", { "aria-hidden": "true" }, [icon(call.status ? "phone" : "clock", { size: 16 })]),
      el("div.lai-appt__body", {}, [
        el("div.lai-appt__top", {}, [
          el("span.lai-appt__status", {}, [call.status || (confirmed ? "Meeting confirmed" : "Tentative")]),
          el("span.lai-appt__when", { title: confirmed && when ? "Dubai time" : null }, [main]),
        ]),
        el("div.lai-appt__lines", {}, lines),
        call.taken,
      ]),
      call.button,
      el("button.lai-btn.lai-btn--ghost.lai-btn--sm.lai-appt__cancel", {
        type: "button",
        title: "Cancel this meeting. No reminder goes out for it.",
        onclick: confirmCancel,
      }, ["Cancel meeting"]),
    ]);
  }

  function confirmCancel() {
    const appointment = state.conversation?.lead_ai_appointment;
    if (!appointment) return;
    const when = String(appointment.when || "").trim();
    const keep = el("button.lai-btn.lai-btn--ghost", { type: "button", onclick: () => dialog.close() }, ["Keep the meeting"]);
    const cancel = el("button.lai-btn.lai-btn--danger", {
      type: "button",
      onclick: async () => {
        cancel.disabled = true;
        keep.disabled = true;
        try {
          const row = await leadAiApi.cancelAppointment(state.id);
          dialog.close();
          toast("Meeting cancelled.");
          if (state.destroyed) return;
          detailSeq += 1;
          applyLeadAi(row);
        } catch (error) {
          if (error?.code === "http_409") {
            // Already gone (the customer cancelled, or someone else did): show what is there now.
            dialog.close();
            toast(error.message || "This chat has no open meeting.", "err");
            if (!state.destroyed) refreshDetail();
            return;
          }
          cancel.disabled = false;
          keep.disabled = false;
          toast(`Could not cancel the meeting: ${error.message}`, "err");
        }
      },
    }, ["Cancel meeting"]);
    const dialog = chatModal("Cancel this meeting?", el("div.lai-confirm", {}, [
      el("p", {}, [
        `${contactName(state.conversation)}'s meeting${when ? ` on ${when}` : ""} will be cancelled. `,
        "No reminder goes out for it, and the CRM record gets a note.",
      ]),
      el("p.lai-confirm__note", {}, ["The customer is not told. Write to them yourself if they should know."]),
      el("div.lai-confirm__actions", {}, [keep, cancel]),
    ]));
    keep.focus(); // as in confirmMove
  }

  /** Looks at the card again when the server will not say it changed (see top). */
  function planRechecks(appointment) {
    clearTimeout(timers.due);
    timers.due = null;
    if (!appointment || state.destroyed) return;
    const due = Date.parse(appointment.reminder_due_at || "");
    if (due && !appointment.reminder_sent_at && !appointment.reminder_error) {
      const wait = due - Date.now() + REMINDER_RECHECK_MS;
      if (wait > 0 && wait < RECHECK_HORIZON_MS) timers.due = setTimeout(() => refreshDetail(), wait);
    }
    const crmPending = !appointment.crm_synced_at && !appointment.crm_error;
    // A meeting booked later in the same open chat gets its own looks.
    if (appointment.id !== crmFor) {
      crmFor = appointment.id;
      crmChecks = 0;
    }
    if (crmPending && !timers.crm && crmChecks < CRM_RECHECK_MS.length) {
      timers.crm = setTimeout(() => {
        timers.crm = null;
        refreshDetail();
      }, CRM_RECHECK_MS[crmChecks]);
      crmChecks += 1;
    }
  }

  /* ---------------------------------------------------- AI is writing */

  function setThinking(on) {
    clearTimeout(timers.thinking);
    timers.thinking = null;
    const stick = nearBottom();
    thinking.hidden = !on;
    if (on) timers.thinking = setTimeout(() => setThinking(false), THINKING_MAX_MS);
    if (stick) list.scrollTop = list.scrollHeight;
  }

  /* ---------------------------------------------------------- messages */

  function renderMessages({ scroll } = {}) {
    const previousHeight = list.scrollHeight;
    const previousTop = list.scrollTop;
    clear(list);
    state.lastDay = "";
    if (!state.exhausted && state.messages.length) {
      list.append(el("button.lai-thread__older", { type: "button", onclick: loadOlder }, ["Load earlier messages"]));
    }
    if (!state.messages.length) {
      list.append(el("div.lai-thread__hint.lai-thread__hint--empty", {}, ["No messages yet."]));
      return;
    }
    for (const message of state.messages) appendNode(message);
    if (scroll === "bottom") list.scrollTop = list.scrollHeight;
    else if (scroll === "preserve") list.scrollTop = list.scrollHeight - previousHeight + previousTop;
  }

  /** Adds one bubble at the end (with a day separator when the day changes). */
  function appendNode(message) {
    list.querySelector(".lai-thread__hint--empty")?.remove();
    const day = dayKey(message.created_at);
    if (day && day !== state.lastDay) {
      list.append(el("div.lai-day", {}, [dayLabel(message.created_at)]));
      state.lastDay = day;
    }
    list.append(bubble(message));
  }

  function nearBottom() {
    return list.scrollHeight - list.scrollTop - list.clientHeight < 120;
  }

  function openImage(message) {
    const images = imagesInThread(state.messages);
    const at = Math.max(0, images.findIndex((i) => String(i.id) === String(message.id)));
    openLightbox(images, at);
  }

  function bubble(message) {
    if (message.kind === "system") {
      return el("div.lai-msg.lai-msg--system", { "data-id": message.id ?? "" }, [message.body || ""]);
    }
    const outbound = message.direction === "out";
    const kind = String(message.kind || "").toLowerCase();
    const source = String(message.source || "");
    // AI messages have no sent_by; their source says who wrote them.
    const fromAi = outbound && AI_SOURCES.has(source);
    const reminder = outbound && source === REMINDER_SOURCE;
    const followUp = outbound && source === FOLLOW_UP_SOURCE;
    const media = mediaMessageNode(message, { onImageClick: openImage, formatBytes });
    const special = specialMessageNode(message);
    const bodyText = String(message.body || "").trim();
    // Only a customer's tap is a button reply. Our own button message (the
    // meeting reminder) is drawn as ours, with its buttons listed under it.
    const isButtonReply = !outbound && (kind === "button" || kind === "interactive");
    const templateLine =
      !bodyText && message.template_name
        ? el("div.lai-msg__tpl", {}, [el("span.lai-msg__tpl-badge", {}, ["Template"]), message.template_name])
        : null;
    const text = bodyText && !special
      ? el("div.lai-msg__text", {}, [isButtonReply ? buttonReplyTag(kind) : null, message.body])
      : null;
    const gloss = fromAi ? String(message.ai_gloss || "").trim() : "";
    const glossNode = gloss
      ? el("div.lai-msg__gloss", {}, [el("span.lai-msg__gloss-label", {}, ["English: "]), gloss])
      : null;
    const footer = kind === "template" ? templateFooterNode(message) : null;
    const buttons = kind === "template" ? templateButtonsRow(message) : null;
    const chips = reminder ? reminderChips(message) : null;
    const empty = !media && !special && !text && !templateLine && !footer
      ? el("div.lai-msg__empty", {}, [fallbackLabel(message)])
      : null;
    const failed = outbound && (message.status === "failed" || message.status === "exhausted");
    const failure = failed ? failureText(message) : "";
    const tick = outbound ? TICKS[message.status] : null;
    const author =
      outbound && message.sent_by?.display_name && String(message.sent_by.id) !== String(me?.id)
        ? message.sent_by.display_name
        : "";
    const badge = fromAi
      ? el("span.lai-msg__badge.lai-msg__badge--ai", {
          title: source === "leadai_tap" ? "The Lead AI's answer to a reminder button" : "Written by the Lead AI assistant",
        }, [icon("zap", { size: 10 }), "AI"])
      : reminder
        ? el("span.lai-msg__badge.lai-msg__badge--reminder", { title: "The meeting reminder the Lead AI sent" }, [
            icon("bell", { size: 10 }),
            "Reminder",
          ])
        : followUp
          ? el("span.lai-msg__badge.lai-msg__badge--followup", { title: "The automatic follow-up the Lead AI sent" }, [
              icon("clock", { size: 10 }),
              "Follow-up",
            ])
          : null;
    const classes = [
      outbound ? "lai-msg--out" : "lai-msg--in",
      fromAi ? "lai-msg--ai" : "",
      reminder ? "lai-msg--reminder" : "",
    ].filter(Boolean).join(" ");

    return el("div.lai-msg", { class: classes, "data-id": message.id ?? "" }, [
      el("div.lai-msg__bubble", {}, [
        special,
        media,
        templateLine,
        text,
        glossNode,
        footer,
        empty,
        failure && !empty ? el("div.lai-msg__error", {}, [failure]) : null,
        el("div.lai-msg__foot", {}, [
          badge,
          author ? el("span.lai-msg__author", {}, [author]) : null,
          el("span", {}, [timeOf(message.created_at)]),
          tick
            ? el("span.lai-tick", { class: tick.className || "", title: failure || tick.label }, [icon(tick.name, { size: 14 })])
            : null,
        ]),
      ]),
      buttons,
      chips,
    ]);
  }

  function replaceNode(oldId, message) {
    const node = list.querySelector(`[data-id="${CSS.escape(String(oldId))}"]`);
    if (node) node.replaceWith(bubble(message));
  }

  /** A live or sent message: replace what we hold, or add it at the end. */
  function upsertMessage(message, { appendUnknown = true } = {}) {
    const index = state.messages.findIndex((m) => String(m.id) === String(message.id));
    if (index !== -1) {
      state.messages[index] = { ...state.messages[index], ...message };
      replaceNode(message.id, state.messages[index]);
      return;
    }
    // The echo of our own reply can arrive before the HTTP answer: take the
    // place of its draft instead of drawing it twice. Only this agent's own
    // message may: the AI (no sender) or a colleague can send the same words,
    // and their row must not swallow a draft that is still on its way.
    const mine = me?.id != null && message.sent_by?.id != null && String(message.sent_by.id) === String(me.id);
    const draftIndex =
      mine && message.direction === "out" && String(message.kind || "text") === "text"
        ? state.messages.findIndex((m) => m.draft && m.body === message.body)
        : -1;
    if (draftIndex !== -1) {
      const draftId = state.messages[draftIndex].id;
      state.messages[draftIndex] = message;
      replaceNode(draftId, message);
      return;
    }
    if (!appendUnknown) return;
    const stick = nearBottom() || message.direction === "out";
    state.messages.push(message);
    appendNode(message);
    if (stick) list.scrollTop = list.scrollHeight;
  }

  /* ----------------------------------------------------------- composer */

  function renderComposer() {
    teardownFiles?.();
    teardownFiles = null;
    state.input = null;
    state.submit = null;
    const conversation = state.conversation;
    if (!conversation) {
      clear(composer);
      return;
    }
    state.composerOpen = Boolean(conversation.is_session_open);

    if (!conversation.is_session_open) {
      clear(composer).append(
        el("div.lai-locked", {}, [
          el("div.lai-locked__text", {}, [
            "The 24-hour window is closed. Only an approved template can go out until the customer writes back.",
          ]),
          el("button.lai-btn.lai-btn--primary", { type: "button", onclick: openTemplates }, [
            icon("file", { size: 15 }),
            "Send template",
          ]),
        ])
      );
      return;
    }

    const input = el("textarea.lai-input", {
      rows: 1,
      placeholder: "Type a reply",
      onkeydown: (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          submit();
        }
      },
      oninput: () => {
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
      },
    });
    state.input = input;
    const attach = el("button.lai-btn.lai-btn--icon", { type: "button", title: "Attach a file" }, [icon("paperclip", { size: 17 })]);
    const templates = el("button.lai-btn.lai-btn--icon", { type: "button", title: "Send a template", onclick: openTemplates }, [
      icon("file", { size: 17 }),
    ]);
    const send = el("button.lai-btn.lai-btn--send", { type: "button", title: "Send", onclick: submit }, [icon("send", { size: 17 })]);

    async function submit() {
      const body = input.value.trim();
      if (!body || state.sending) return;
      state.sending = true;
      send.disabled = true;
      const draft = {
        id: `draft-${Date.now()}`,
        draft: true,
        direction: "out",
        kind: "text",
        body,
        status: "queued",
        created_at: new Date().toISOString(),
        sent_by: me ? { id: me.id, display_name: me.display_name } : null,
      };
      input.value = "";
      input.style.height = "auto";
      state.messages.push(draft);
      appendNode(draft);
      list.scrollTop = list.scrollHeight;
      try {
        const real = await inbox.send(state.id, { kind: "text", body });
        settleDraft(draft.id, real);
        if (state.draftEdited !== undefined && state.conversation?.lead_ai_ai?.draft) {
          // The co-pilot's draft went out in the agent's own words (or as it was): its fate is recorded.
          state.draftEdited = undefined;
          leadAiApi.draftUsed(state.id, body).then((row) => { detailSeq += 1; applyLeadAi(row); }).catch(() => {});
        }
      } catch (error) {
        // A failed send may already have arrived live as its own failed row.
        settleDraft(draft.id, null, error.message);
      } finally {
        state.sending = false;
        send.disabled = false;
        (state.input || input).focus();
      }
    }

    clear(composer).append(el("div.lai-composer", {}, [attach, templates, input, send]));
    state.submit = submit; // the co-pilot's "Send as me" sends through the same box (renderDraft)
    teardownFiles = bindFileSources({
      button: attach,
      dropZone: list,
      pasteTarget: input,
      onFile: (file) =>
        openAttachmentDialog(file, {
          conversationId: state.id,
          onSent: (message) => {
            if (message) upsertMessage(message);
          },
        }),
    });
  }

  /** The HTTP answer for a draft: becomes the real row, or a failed bubble. */
  function settleDraft(draftId, real, errorText = "") {
    const index = state.messages.findIndex((m) => m.id === draftId);
    if (index === -1) return; // already replaced by its live echo
    if (real?.id !== undefined && state.messages.some((m, i) => i !== index && String(m.id) === String(real.id))) {
      state.messages.splice(index, 1);
      list.querySelector(`[data-id="${CSS.escape(String(draftId))}"]`)?.remove();
      return;
    }
    const next = real ? { ...real } : { ...state.messages[index], draft: false, status: "failed", error_detail: errorText };
    state.messages[index] = next;
    replaceNode(draftId, next);
  }

  function openTemplates() {
    if (!state.conversation) return;
    openTemplateComposer({
      mode: "reply",
      conversation: state.conversation,
      templatesFor: async () => asList(await inbox.conversationTemplates(state.id), "templates"),
      // The composer outlives this chat when the agent opened another meanwhile.
      onSent: () => {
        if (!state.destroyed) load();
      },
    });
  }

  /* -------------------------------------------------------------- live */

  function onEvent(event, data) {
    const message = data?.message;
    const conversation = data?.conversation;
    // The assistant's own events and alerts carry flat ids, not objects.
    const id = conversation?.id ?? message?.conversation_id ?? data?.conversation_id;
    if (String(id) !== String(state.id)) return;
    if (event === "leadai.ai.state") {
      thinkingSeq += 1;
      setThinking(data?.state === "thinking");
      return;
    }
    if (event === "leadai.ai.changed" || event === "leadai.alert") {
      refreshSoon();
      return;
    }
    if (event === "leadai.message.new" && message) {
      upsertMessage(message);
      if (conversation) setConversation(conversation);
      if (message.direction === "in") {
        state.conversation = { ...(state.conversation || {}), unread_count: 1 };
        markRead();
      } else if (AI_SOURCES.has(String(message.source || ""))) {
        thinkingSeq += 1;
        setThinking(false);
      }
      // The reminder going out changes the meeting card, and no other event says so.
      if (message.direction === "out" && message.source === REMINDER_SOURCE) refreshSoon();
      return;
    }
    if (event === "leadai.message.status" && message) {
      // Status receipts only update rows already on screen.
      upsertMessage(message, { appendUnknown: false });
      return;
    }
    if (conversation) setConversation(conversation);
  }

  function onVisible() {
    if (document.visibilityState === "visible") markRead();
  }
  document.addEventListener("visibilitychange", onVisible);

  return {
    id: conversationId,
    onEvent,
    reload: () => load(),
    highlight: (messageId) => load({ highlight: messageId }),
    destroy() {
      state.destroyed = true;
      for (const dialog of [...dialogs]) dialog.close();
      teardownFiles?.();
      clearTimeout(timers.thinking);
      clearTimeout(timers.due);
      clearTimeout(timers.crm);
      document.removeEventListener("visibilitychange", onVisible);
    },
  };
}
