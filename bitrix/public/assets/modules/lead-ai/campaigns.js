/**
 * Lead AI → Campaigns: history of every Lead AI CRM campaign (queue + delivered/read).
 *
 * Tools → Campaigns opens a wide dialog: list on the left (newest first), detail on the
 * right. Only campaigns with a LeadAiCampaign row. Counts: pending / sent / delivered /
 * read / failed / skipped / retrying. While a campaign is still running, the open detail
 * refreshes every few seconds. No recipient phones and no Resend in v1.
 */

import { el, clear } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { leadAiApi } from "./api.js";
import { screenModal } from "./thread.js";

const POLL_MS = 5000;
const LIVE = new Set(["queued", "running", "retrying"]);

let campaignsDialog = null;
let pollTimer = null;
let activeId = null;

/** Tools menu entry. */
export function campaignsButton() {
  return el(
    "button.lai-btn.lai-btn--ghost.lai-bar__campaigns",
    {
      type: "button",
      role: "menuitem",
      title: "Lead AI campaigns: sent, failed, delivered and read",
      onclick: () => openCampaignsDialog(),
    },
    [icon("send", { size: 15 }), "Campaigns"]
  );
}

export function closeCampaignsDialog() {
  stopPoll();
  campaignsDialog?.close();
}

export function openCampaignsDialog() {
  if (campaignsDialog) return;
  activeId = null;
  const list = el("div.lai-camp__list", {}, [el("p.lai-camp__note", {}, ["Loading…"])]);
  const detail = el("div.lai-camp__detail", {}, [
    el("div.lai-camp__empty", {}, [
      el("div.lai-camp__empty-title", {}, ["Select a campaign"]),
      el("p.lai-camp__note", {}, ["Sent, delivered, read and failed counts for Lead AI sends."]),
    ]),
  ]);
  const body = el("div.lai-camp", {}, [
    el("aside.lai-camp__list-wrap", {}, [
      el("div.lai-camp__head", {}, [
        el("h3.lai-camp__heading", {}, ["Past campaigns"]),
        el("p.lai-camp__blurb", {}, ["Lead AI only · newest first"]),
      ]),
      list,
    ]),
    detail,
  ]);
  const dialog = screenModal("Lead AI campaigns", body, {
    wide: true,
    onClose: () => {
      stopPoll();
      if (campaignsDialog === dialog) campaignsDialog = null;
      activeId = null;
    },
  });
  dialog.box.classList.add("lai-modal--campaigns");
  campaignsDialog = dialog;

  loadList(list, detail);
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPoll(detail) {
  stopPoll();
  if (!activeId || !LIVE.has(String(detail.dataset.status || ""))) return;
  pollTimer = setInterval(() => {
    if (!campaignsDialog || !activeId) {
      stopPoll();
      return;
    }
    refreshDetail(detail, activeId, { quiet: true });
  }, POLL_MS);
}

function n(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("en-US") : "0";
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function statusClass(status) {
  const s = String(status || "").toLowerCase();
  if (s === "done") return "is-done";
  if (s === "failed" || s === "cancelled") return "is-bad";
  if (LIVE.has(s)) return "is-live";
  return "is-idle";
}

async function loadList(listEl, detailEl) {
  try {
    const data = await leadAiApi.campaigns({ limit: 50 });
    if (!campaignsDialog) return;
    const rows = Array.isArray(data?.results) ? data.results : [];
    clear(listEl);
    if (!rows.length) {
      listEl.append(
        el("p.lai-camp__note", {}, ["No Lead AI campaigns yet. Send one from the CRM popup with Lead AI on."])
      );
      return;
    }
    for (const row of rows) {
      listEl.append(rowButton(row, detailEl, listEl));
    }
    // Open the newest by default.
    const first = rows[0];
    if (first) {
      activeId = first.id;
      markActive(listEl, first.id);
      renderDetail(detailEl, first);
      startPoll(detailEl);
    }
  } catch (error) {
    if (!campaignsDialog) return;
    clear(listEl).append(
      el("p.lai-camp__note.lai-camp__note--err", {}, [`Could not load campaigns: ${error.message}`])
    );
  }
}

function rowButton(row, detailEl, listEl) {
  const btn = el(
    "button.lai-camp__row",
    {
      type: "button",
      "data-id": String(row.id),
      onclick: () => {
        activeId = row.id;
        markActive(listEl, row.id);
        refreshDetail(detailEl, row.id);
      },
    },
    [
      el("div.lai-camp__row-top", {}, [
        el("strong.lai-camp__row-name", {}, [row.name || `Campaign #${row.id}`]),
        el(`span.lai-camp__status.${statusClass(row.status)}`, {}, [String(row.status || "")]),
      ]),
      el("div.lai-camp__row-meta", {}, [
        when(row.created_at),
        row.number ? ` · +${row.number}` : "",
      ].filter(Boolean).join("")),
      el("div.lai-camp__row-counts", {}, [
        `${n(row.sent)} / ${n(row.total)} sent`,
        Number(row.failed) > 0 ? ` · ${n(row.failed)} failed` : "",
        Number(row.delivered) > 0 ? ` · ${n(row.delivered)} delivered` : "",
        Number(row.read) > 0 ? ` · ${n(row.read)} read` : "",
      ].filter(Boolean).join("")),
    ]
  );
  return btn;
}

function markActive(listEl, id) {
  for (const node of listEl.querySelectorAll(".lai-camp__row")) {
    node.classList.toggle("is-on", String(node.dataset.id) === String(id));
  }
}

async function refreshDetail(detailEl, id, { quiet = false } = {}) {
  if (!quiet) {
    clear(detailEl).append(el("p.lai-camp__note", {}, ["Loading…"]));
  }
  try {
    const row = await leadAiApi.campaign(id);
    if (!campaignsDialog || String(activeId) !== String(id)) return;
    renderDetail(detailEl, row);
    startPoll(detailEl);
  } catch (error) {
    if (!campaignsDialog || String(activeId) !== String(id)) return;
    clear(detailEl).append(
      el("p.lai-camp__note.lai-camp__note--err", {}, [`Could not load campaign: ${error.message}`])
    );
    stopPoll();
  }
}

function tile(label, value, { warn = false } = {}) {
  return el(`div.lai-camp__tile${warn ? ".lai-camp__tile--warn" : ""}`, {}, [
    el("div.lai-camp__tile-n", {}, [n(value)]),
    el("div.lai-camp__tile-l", {}, [label]),
  ]);
}

function renderDetail(detailEl, row) {
  clear(detailEl);
  detailEl.dataset.status = String(row.status || "");
  const settled = Number(row.sent || 0) + Number(row.failed || 0) + Number(row.skipped || 0);
  const pct = Number(row.total) > 0 ? Math.round((settled / Number(row.total)) * 100) : 0;
  const fill = el("div.lai-camp__bar-fill");
  fill.style.width = `${Math.min(100, pct)}%`;

  const creator = row.created_by?.display_name || "";
  const playbook =
    row.playbook === "ic_shops"
      ? "International City — all"
      : row.playbook === "general"
        ? "General"
        : row.playbook || "";

  detailEl.append(
    el("div.lai-camp__progress", {}, [
      el("div.lai-camp__progress-top", {}, [
        el("strong", {}, [row.name || `Campaign #${row.id}`]),
        el(`span.lai-camp__status.${statusClass(row.status)}`, {}, [String(row.status || "")]),
      ]),
      el("div.lai-camp__bar", {}, [fill]),
      el("div.lai-camp__progress-meta", {}, [`${pct}% settled · ${when(row.created_at)}`]),
    ]),
    el("div.lai-camp__tiles", {}, [
      tile("total", row.total),
      tile("sent", row.sent),
      tile("delivered", row.delivered),
      tile("read", row.read),
      tile("failed", row.failed, { warn: Number(row.failed) > 0 }),
      tile("skipped", row.skipped),
      tile("pending", row.pending),
      tile("retrying", row.retrying, { warn: Number(row.retrying) > 0 }),
    ]),
    el("dl.lai-camp__meta", {}, [
      meta("Template", row.template_name || "—"),
      meta("From", row.number ? `+${row.number}${row.number_title ? ` · ${row.number_title}` : ""}` : "—"),
      meta("Playbook", playbook || "—"),
      meta("Community", row.community || "International City"),
      meta("Sent by", creator || "—"),
      meta("Started", when(row.started_at) || "—"),
      meta("Finished", when(row.finished_at) || (LIVE.has(String(row.status || "")) ? "Still running" : "—")),
    ])
  );
  if (row.error_detail) {
    detailEl.append(el("p.lai-camp__note.lai-camp__note--err", {}, [String(row.error_detail)]));
  }
}

function meta(label, value) {
  return el("div.lai-camp__meta-row", {}, [
    el("dt", {}, [label]),
    el("dd", {}, [value]),
  ]);
}
