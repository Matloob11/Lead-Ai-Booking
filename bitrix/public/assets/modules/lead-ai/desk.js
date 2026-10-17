/**
 * The agent desk on the Lead AI screen (batch 2e; spec §2.12 and §3.3; board T100, T94; Q30, Q37, Q39).
 *
 * Nobody is named: the agents with Lead AI access (Agents & access) follow every
 * Lead AI chat from this screen, so the desk is the record that stays (an alert
 * shows for seconds). Layout B (62aa348) left the desk's places in the screen,
 * hidden; this module makes the pieces, and screen.js and thread.js put them
 * there:
 *
 * - deskRail: "Needs a person" and "Today" in the left rail, each with its
 *   count. They are list views of the Lead AI chats: ?needs=1 (handed over or a
 *   broker with nobody from the team writing since, a held time, a held full
 *   name; the longest wait first) and ?today=1 (every open visit and call that
 *   starts today, Dubai time, by time). The counts come with the list's first
 *   page (desk_counts) and from GET /api/leadai/desk/.
 * - trackFilters: Shops, Rent, Sale and Other beside Brokers (?track=), one at
 *   a time; pressed again, it lets go.
 * - deskLine: what a row of those views says ("Handed over: asked for a call ·
 *   waiting 25 min", "Call 4:30 PM · Taken by Omar").
 * - trackChip: "Rent · Studio", "Shop", "Not known yet", in place of "IC shops"
 *   (lead_ai_ai.track_label).
 * - callParts: "Sales call" on the meeting card, I'll call until someone takes
 *   it, then "Taken by …" (POST …/appointment/take/: the first agent wins; a
 *   second hears who has it, 409 {taken_by}). The customer is never told who.
 *
 * What an agent may open is the server's to decide. English only; every node is
 * built, and nothing a customer or an agent typed goes through innerHTML.
 */

import { debounce, el, toast } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { leadAiApi } from "./api.js";

/** The rail's list views besides "Chats". */
export const DESK_TABS = ["needs", "today"];

/** The filters beside Brokers, as ?track= takes them. */
const TRACKS = [
  ["shop", "Shops", "Only the chats about a shop to rent"],
  ["rent", "Rent", "Only the chats about a studio or a one-bedroom to rent"],
  ["sale", "Sale", "Only the chats about a studio or a one-bedroom to buy"],
  ["other", "Other", "Only the chats about something else: a bigger home, another area, buying a shop"],
];

/** The chip's colour per track (lead-ai.css, lai-desk-chip--*). */
const CHIP_TONE = { shop: "shop", rent: "rent", sale: "sale", other: "other", "": "unknown" };

// The counts are read again this long after the last change that may move them.
const COUNTS_AFTER_MS = 800;

export function isDeskTab(tab) {
  return DESK_TABS.includes(tab);
}

/** The list's query for a view and a track filter. */
export function deskParams(tab, track = "") {
  return { track: track || "", needs: tab === "needs", today: tab === "today" };
}

function plural(n, one, many) {
  return n === 1 ? one : many;
}

/** "25 min", "2 h 10 min", "3 days" since then; "" for no moment. */
export function waitText(iso) {
  const at = Date.parse(iso || "");
  if (!at) return "";
  const minutes = Math.max(0, Math.round((Date.now() - at) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  return `${days} ${plural(days, "day", "days")}`;
}

/**
 * Needs a person and Today in the rail. `onSelect(tab)` is the screen's own
 * tab switch; `active(tab)` marks the one showing.
 */
export function deskRail({ onSelect }) {
  const counts = { needs: 0, today: 0 };
  let gone = false;

  function railButton(tab, glyph, label, title) {
    const badge = el("span.lai-desk-count", { hidden: true, "aria-hidden": "true" });
    const node = el("button.lai-rail__btn.lai-desk-rail", { type: "button", title, onclick: () => onSelect(tab) }, [
      icon(glyph, { size: 16 }),
      el("span.lai-rail__label", {}, [label]),
      badge,
    ]);
    return { node, badge, label, title };
  }

  const needs = railButton(
    "needs",
    "bell",
    "Needs a person",
    "Chats waiting for someone from the team: handed over, a broker, a held time or a held full name. The longest wait first."
  );
  const today = railButton("today", "clock", "Today", "Every visit and call that starts today, by time.");
  const parts = { needs, today };

  function draw() {
    for (const [tab, part] of Object.entries(parts)) {
      const n = Number(counts[tab]) || 0;
      part.badge.textContent = n > 99 ? "99+" : String(n);
      part.badge.hidden = !n;
      part.badge.classList.toggle("lai-desk-count--urgent", tab === "needs" && n > 0);
      // The count is read out with the label, as the badge itself is hidden from screen readers.
      part.node.setAttribute("aria-label", n ? `${part.label}, ${n}` : part.label);
    }
  }

  function setCounts(next) {
    if (!next || typeof next !== "object" || gone) return;
    for (const tab of DESK_TABS) {
      const n = Number(next[tab]);
      if (Number.isFinite(n) && n >= 0) counts[tab] = n;
    }
    draw();
  }

  const refresh = debounce(async () => {
    if (gone) return;
    try {
      setCounts(await leadAiApi.deskCounts());
    } catch {
      /* the counts are a hint; the list itself loads the truth */
    }
  }, COUNTS_AFTER_MS);

  draw();
  return {
    buttons: [needs.node, today.node],
    active(tab) {
      for (const [name, part] of Object.entries(parts)) {
        part.node.classList.toggle("is-on", tab === name);
        part.node.setAttribute("aria-pressed", String(tab === name));
      }
    },
    setCounts,
    refresh,
    destroy() {
      gone = true;
    },
  };
}

/** Shops, Rent, Sale and Other beside Brokers: one at a time (`onChange(track)`, "" when let go). */
export function trackFilters({ onChange }) {
  let current = "";
  const buttons = TRACKS.map(([value, label, title]) =>
    el("button.lai-filter.lai-desk-filter", {
      type: "button",
      title,
      "aria-pressed": "false",
      "data-track": value,
      onclick: () => set(current === value ? "" : value, true),
    }, [label])
  );

  function set(value, announce = false) {
    current = value;
    for (const button of buttons) {
      const on = button.dataset.track === current;
      button.classList.toggle("is-on", on);
      button.setAttribute("aria-pressed", String(on));
    }
    if (announce) onChange?.(current);
  }

  return {
    buttons,
    value: () => current,
    reset: () => set(""),
  };
}

/** What the list says when a desk view or a track filter holds nothing. */
export function deskEmptyText(tab, track = "") {
  const which = TRACKS.find(([value]) => value === track)?.[1];
  if (tab === "needs") {
    return which
      ? `No ${which.toLowerCase()} chat needs a person now.`
      : "Nobody is waiting for a person now. Handed-over chats, brokers and held times show here until someone from the team writes.";
  }
  if (tab === "today") {
    return which ? `No ${which.toLowerCase()} visit or call today.` : "No visit or call today.";
  }
  return which ? `No ${which.toLowerCase()} chats.` : "";
}

/** A Needs a person or Today row's own line (lead_ai_desk); null on any other row. */
export function deskLine(row) {
  const part = row?.lead_ai_desk;
  if (!part || typeof part !== "object") return null;
  if (part.view === "needs") {
    const reasons = (Array.isArray(part.reasons) ? part.reasons : []).map((text) => String(text ?? "").trim()).filter(Boolean);
    const wait = waitText(part.since);
    const kinds = Array.isArray(part.kinds) ? part.kinds : [];
    return el("div.lai-desk-line.lai-desk-line--needs", { title: reasons.join(". ") || null }, [
      icon(kinds.includes("held") && kinds.length === 1 ? "clock" : "alert", { size: 12 }),
      el("span.lai-desk-line__text", {}, [reasons[0] || "Needs a person"]),
      reasons.length > 1 ? el("span.lai-desk-line__more", {}, [`+${reasons.length - 1}`]) : null,
      wait ? el("span.lai-desk-line__wait", {}, [`waiting ${wait}`]) : null,
    ]);
  }
  if (part.view === "today") {
    const label = String(part.label || "").trim();
    const taken = String(part.taken_by || "").trim();
    return el("div.lai-desk-line.lai-desk-line--today", { class: part.kind === "held" ? "lai-desk-line--held" : "" }, [
      icon(part.kind === "call" ? "phone" : "clock", { size: 12 }),
      el("span.lai-desk-line__text", {}, [label || "Today"]),
      taken ? el("span.lai-desk-line__taken", {}, [`Taken by ${taken}`]) : null,
      !taken && part.kind === "call" ? el("span.lai-desk-line__open", {}, ["Not taken yet"]) : null,
    ]);
  }
  return null;
}

/** The track chip in place of "IC shops", from lead_ai_ai.track_label; null when the server sends none. */
export function trackChip(conversation) {
  const ai = conversation?.lead_ai_ai;
  const label = String(ai?.track_label || "").trim();
  if (!label) return null;
  const track = String(ai?.track || "");
  return el(
    "span.lai-chip.lai-desk-chip",
    {
      class: `lai-desk-chip--${CHIP_TONE[track] || "unknown"}`,
      title: track ? `What the customer wants, as the AI reads it: ${label}` : "The customer has not said what they want yet",
    },
    [label]
  );
}

/**
 * The call card's desk parts. `take()` posts I'll call and resolves to the
 * chat's row; `onRow(row)` draws it; `onStale()` reads the chat again when
 * someone else took the call first (409) or it is gone; `isGone()` says the
 * chat was closed meanwhile.
 *
 * @returns {{status: string, taken: HTMLElement|null, button: HTMLElement|null}}
 */
export function callParts(appointment, { me, take, onRow, onStale, isGone } = {}) {
  const callLabel = String(appointment?.call_label || "").trim();
  if (!callLabel) return { status: "", taken: null, button: null };
  const confirmed = appointment.status === "confirmed";
  const status = confirmed ? callLabel : `${callLabel} held`;
  const takenBy = String(appointment.taken_by || "").trim();
  if (takenBy) {
    const mine = me?.id != null && String(appointment.taken_by_id) === String(me.id);
    const node = el("span.lai-desk-taken", { title: "The customer is not told who calls them." }, [
      icon("userCheck", { size: 12 }),
      el("span", {}, [mine ? "Taken by you" : `Taken by ${takenBy}`]),
    ]);
    return { status, taken: node, button: null };
  }
  if (!appointment.takeable) return { status, taken: null, button: null };
  const button = el("button.lai-btn.lai-btn--primary.lai-btn--sm.lai-desk-call", {
    type: "button",
    title: "Take this call: the others see it is yours. Call them from your work phone at the time.",
    onclick: async () => {
      button.disabled = true;
      try {
        const row = await take();
        if (isGone?.()) return;
        toast("The call is yours. Call them at the time.");
        onRow?.(row);
      } catch (error) {
        if (isGone?.()) return;
        button.disabled = false;
        if (error?.code === "http_409") {
          // Someone was quicker, or the call is gone: say who, and show the card as it is now.
          const who = String(error?.detail?.taken_by || "").trim();
          toast(who ? `${who} has already taken this call.` : error.message || "This chat has no open call.", "err");
          onStale?.();
          return;
        }
        toast(`Could not take the call: ${error.message}`, "err");
      }
    },
  }, [icon("phone", { size: 12 }), "I'll call"]);
  return { status, taken: null, button };
}
