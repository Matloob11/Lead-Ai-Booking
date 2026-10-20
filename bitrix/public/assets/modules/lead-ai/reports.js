/**
 * Lead AI → Reports: the daily digests (apps/leadai/assistant/digest.py).
 *
 * "Reports" in the Lead AI bar opens a dialog with today so far (counted now),
 * yesterday's digest as it was sent to Bitrix, and one row per stored day:
 * replies, late answers, handovers (new / taken by a person / waiting), the
 * co-pilot's drafts, bookings, opt-outs and the model's cost. Everyone with the
 * Lead AI screen may read it; nothing here writes. The digest itself is sent
 * by the sweep at eight in the morning Dubai, to the admins and the alert list.
 *
 * Counts only: no customer's words or number ever reach this dialog.
 */

import { el, clear } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { leadAiApi } from "./api.js";
import { screenModal } from "./thread.js";

const DAYS = 14;
let reportsDialog = null;

/** The bar's "Reports" button. */
export function reportsButton() {
  return el("button.lai-btn.lai-btn--ghost.lai-bar__reports", {
    type: "button",
    title: "The daily digests: replies, handovers, bookings, opt-outs and the model's cost",
    onclick: () => openReportsDialog(),
  }, [icon("chart", { size: 15 }), "Reports"]);
}

export function closeReportsDialog() {
  reportsDialog?.close();
}

export function openReportsDialog() {
  if (reportsDialog) return;
  const body = el("div.lai-rep", {}, [el("p.lai-rep__note", {}, ["Loading…"])]);
  const dialog = screenModal("Lead AI reports", body, {
    wide: true,
    onClose: () => {
      if (reportsDialog === dialog) reportsDialog = null;
    },
  });
  dialog.box.classList.add("lai-modal--reports");
  reportsDialog = dialog;

  leadAiApi.digests({ days: DAYS }).then(
    (data) => {
      if (reportsDialog === dialog) render(body, data);
    },
    (error) => {
      if (reportsDialog !== dialog) return;
      clear(body).append(el("p.lai-rep__note.lai-rep__note--err", {}, [`Could not load the reports: ${error.message}`]));
    }
  );
}

function n(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("en-US") : "0";
}

function money(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `$${number.toFixed(2)}` : "$0.00";
}

function dayLabel(iso) {
  const [y, m, d] = String(iso || "").split("-").map(Number);
  if (!y || !m || !d) return String(iso || "");
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

function tile(label, value, { sub = "", warn = false } = {}) {
  return el(`div.lai-rep__tile${warn ? ".lai-rep__tile--warn" : ""}`, {}, [
    el("div.lai-rep__tile-n", {}, [String(value)]),
    el("div.lai-rep__tile-l", {}, [label]),
    sub ? el("div.lai-rep__tile-sub", {}, [sub]) : null,
  ]);
}

function section(title, ...children) {
  return el("section.lai-rep__section", {}, [el("h3.lai-rep__h", {}, [title]), ...children]);
}

function tiles(stats) {
  const turns = stats.turns || {};
  const chats = stats.chats || {};
  const hand = stats.handovers || {};
  const book = stats.bookings || {};
  const opt = stats.opt_outs || {};
  const cost = stats.cost || {};
  const drafts = stats.drafts || {};
  return el("div.lai-rep__tiles", {}, [
    tile("replies", n(turns.replied), { sub: `${n(chats.answered)} chats · ${n(turns.skipped)} skipped · ${n(turns.failed)} failed`, warn: Number(turns.failed) > 0 }),
    tile("late (over a minute)", n(turns.late), { sub: `median ${(Number(turns.p50_ms || 0) / 1000).toFixed(1)} s`, warn: Number(turns.late) > 0 }),
    tile("handovers", n(hand.new), { sub: `${n(hand.taken)} taken · ${n(hand.waiting_now)} waiting now`, warn: Number(hand.waiting_now) > 0 }),
    tile("drafts", n(Number(drafts.sent || 0) + Number(drafts.edited || 0) + Number(drafts.auto || 0)), { sub: `${n(drafts.sent)} sent · ${n(drafts.edited)} edited · ${n(drafts.auto)} by itself` }),
    tile("bookings", n(book.created), { sub: `${n(book.visits)} visits · ${n(book.calls)} calls · ${n(book.confirmed)} confirmed` }),
    tile("opt-outs", n(opt.total), { warn: Number(opt.total) > 0 }),
    tile("model cost", money(cost.usd), { sub: `${n(cost.calls)} calls · ${money(cost.usd_per_reply)} a reply` }),
  ]);
}

function textLines(text) {
  return el("div.lai-rep__text", {}, String(text || "").split("\n").filter(Boolean).map((line, index) => el(index === 0 ? "p.lai-rep__text-head" : "p", {}, [line])));
}

function table(rows) {
  const head = ["Day", "Replies", "Late", "Handovers", "Taken", "Drafts", "Bookings", "Opt-outs", "Cost", "Sent to"];
  const body = rows.map((row) => {
    const stats = row.stats || {};
    const turns = stats.turns || {};
    const hand = stats.handovers || {};
    const book = stats.bookings || {};
    const drafts = stats.drafts || {};
    const cells = [
      dayLabel(row.day),
      n(turns.replied),
      n(turns.late),
      n(hand.new),
      hand.median_minutes == null ? n(hand.taken) : `${n(hand.taken)} (${n(hand.median_minutes)} min)`,
      n(Number(drafts.sent || 0) + Number(drafts.edited || 0) + Number(drafts.auto || 0)),
      n(book.created),
      n((stats.opt_outs || {}).total),
      money((stats.cost || {}).usd),
      Array.isArray(row.sent_to) && row.sent_to.length ? `${row.sent_to.length} user${row.sent_to.length === 1 ? "" : "s"}` : "—",
    ];
    return el("tr", { title: row.text || "" }, cells.map((cell, index) => el(index === 0 ? "th" : "td", { scope: index === 0 ? "row" : null }, [cell])));
  });
  return el("div.lai-rep__scroll", {}, [
    el("table.lai-rep__table", {}, [
      el("thead", {}, [el("tr", {}, head.map((label) => el("th", { scope: "col" }, [label])))]),
      el("tbody", {}, body),
    ]),
  ]);
}

function render(body, data) {
  if (!data || typeof data !== "object") return;
  const today = data.today || {};
  const digests = Array.isArray(data.digests) ? data.digests : [];
  const parts = [
    section(`Today so far (${dayLabel(today.day)}, counted now)`, tiles(today.stats || {})),
  ];
  if (digests.length) {
    const latest = digests[0];
    parts.push(section(`Last digest (${dayLabel(latest.day)})`, textLines(latest.text),
      el("p.lai-rep__note", {}, [
        Array.isArray(latest.sent_to) && latest.sent_to.length
          ? `Sent to ${latest.sent_to.length} Bitrix user${latest.sent_to.length === 1 ? "" : "s"} at ${String(data.digest_hour || 8)}:00 Dubai.`
          : "Stored without a notification (a day the sweep caught up on).",
      ])));
    parts.push(section(`The last ${digests.length} day${digests.length === 1 ? "" : "s"}`, table(digests)));
  } else {
    parts.push(section("Digests", el("p.lai-rep__note", {}, [
      `The first digest is written at ${String(data.digest_hour || 8)}:00 Dubai, the morning after the day it describes, and sent to the panel admins and the Lead AI alert list.`,
    ])));
  }
  clear(body).append(...parts);
}
