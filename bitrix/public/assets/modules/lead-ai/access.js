/**
 * Lead AI access per Bitrix user (apps/leadai/access.py; Matloob 2026-10-23, round 25).
 *
 * A panel admin's screen: the portal's active users, read live from Bitrix, merged with the panel's accounts, each with
 * three grants of its own — All chats (every Lead AI chat, its live feed and its alerts: the same grant as Lead AI
 * access in Agents & access, kept in step both ways), Today (the Today list: every visit and call of the day, and those
 * chats), Needs a person (every chat waiting for someone, and those chats) — plus how many handovers sit on their
 * desk and whether they are a panel admin (who sees everything whatever the switches say). An agent with no grant
 * keeps what they had: their own chats and "My handovers".
 *
 * Opened from the hamburger menu ("Lead AI access", admins only; lead-ai.js). Its own styles are injected once below:
 * the shared stylesheet and the screen module are another session's to edit this week.
 */

import { clear, debounce, el } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { apiFetch } from "../../core/bitrix-sso.js";
import { screenModal } from "./thread.js";

const FLAGS = [
  ["all_chats", "All chats", "Every Lead AI chat on any number, its live feed and its alerts (Lead AI access in Agents & access)."],
  ["today", "Today", "The Today list: every visit and call of the day, and those chats."],
  ["needs", "Needs a person", "The Needs a person list: every chat waiting for someone from the team, and those chats."],
];

const CSS = `
.lai-acc { display: flex; flex-direction: column; gap: 12px; min-height: 240px; }
.lai-acc__top { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.lai-acc__search { flex: 1 1 220px; min-width: 180px; padding: 8px 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.18); background: rgba(255,255,255,0.06); color: inherit; font: inherit; }
.lai-acc__state { font-size: 12px; opacity: 0.75; }
.lai-acc__table { width: 100%; border-collapse: collapse; font-size: 13px; }
.lai-acc__table th, .lai-acc__table td { padding: 8px 6px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.08); vertical-align: middle; }
.lai-acc__table th { font-weight: 600; font-size: 12px; opacity: 0.8; white-space: nowrap; }
.lai-acc__who { display: flex; flex-direction: column; gap: 2px; }
.lai-acc__name { font-weight: 600; }
.lai-acc__sub { font-size: 12px; opacity: 0.7; }
.lai-acc__tag { display: inline-block; padding: 1px 6px; border-radius: 999px; font-size: 11px; background: rgba(255,255,255,0.12); margin-left: 4px; }
.lai-acc__tag--admin { background: rgba(140, 110, 255, 0.35); }
.lai-acc__tag--off { background: rgba(255, 120, 120, 0.25); }
.lai-acc__cell { white-space: nowrap; }
.lai-acc__switch { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.lai-acc__switch input { width: 18px; height: 18px; accent-color: #8c6eff; cursor: pointer; }
.lai-acc__switch input:disabled { cursor: not-allowed; opacity: 0.45; }
.lai-acc__status { font-size: 12px; min-height: 16px; }
.lai-acc__status--bad { color: #ff9b9b; }
.lai-acc__empty { padding: 24px; text-align: center; opacity: 0.7; }
@media (max-width: 760px) { .lai-acc__table th:nth-child(3), .lai-acc__table td:nth-child(3) { display: none; } }
`;

function ensureCss() {
  if (document.getElementById("lai-access-css")) return;
  document.head.append(el("style", { id: "lai-access-css" }, [CSS]));
}

function whenText(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function accountText(row) {
  const account = row.account;
  if (!account) return "No panel account yet (the grants hold from their first sign-in)";
  if (!account.is_active) return "Panel account inactive";
  if (!account.can_official_api) return "No Official API inbox: sees nothing of Lead AI";
  return account.last_login ? `Signed in ${whenText(account.last_login)}` : "Never signed in";
}

/** Opens the screen; returns the dialog. `me` is the signed-in admin (its Bitrix id is never editable). */
export function openAccessDialog({ me } = {}) {
  ensureCss();
  const state = { rows: [], q: "", bitrix: null, mine: "", busy: new Set() };
  const search = el("input.lai-acc__search", {
    type: "search",
    placeholder: "Search by name, position or Bitrix id",
    oninput: debounce(() => {
      state.q = search.value.trim().toLowerCase();
      renderRows();
    }, 150),
  });
  const stateNode = el("span.lai-acc__state");
  const refreshButton = el("button.lai-btn.lai-btn--ghost.lai-btn--sm", { type: "button", title: "Read the portal's users again now", onclick: () => load({ refresh: true }) }, [
    icon("refresh", { size: 14 }),
    "Refresh from Bitrix",
  ]);
  const status = el("div.lai-acc__status", { role: "status" });
  const tableHost = el("div");
  const body = el("div.lai-acc", {}, [
    el("div.lai-acc__top", {}, [search, refreshButton, stateNode]),
    el("p.lai-set__p", {}, [
      "Each switch is one grant on its own. A panel admin sees everything whatever the switches say; an agent with no grant keeps their own chats and \"My handovers\" only.",
    ]),
    tableHost,
    status,
  ]);
  const dialog = screenModal("Lead AI access", body, { wide: true });
  load();
  return dialog;

  function say(text, bad = false) {
    status.textContent = text || "";
    status.classList.toggle("lai-acc__status--bad", Boolean(bad));
  }

  async function load({ refresh = false } = {}) {
    say("Loading…");
    refreshButton.disabled = true;
    try {
      const payload = await apiFetch(`/api/leadai/access/${refresh ? "?refresh=1" : ""}`);
      state.rows = Array.isArray(payload?.results) ? payload.results : [];
      state.bitrix = payload?.bitrix || null;
      state.mine = String(payload?.me || "");
      renderState();
      renderRows();
      say("");
    } catch (error) {
      say(`Could not load the list: ${error.message}`, true);
    } finally {
      refreshButton.disabled = false;
    }
  }

  function renderState() {
    const b = state.bitrix || {};
    const parts = [`${state.rows.length} people`];
    if (b.read_at) parts.push(`Bitrix users read ${whenText(b.read_at)} (${b.users})`);
    if (b.error) parts.push(`Bitrix could not be read: ${b.error}`);
    stateNode.textContent = parts.join(" · ");
  }

  function matches(row) {
    if (!state.q) return true;
    const hay = `${row.name} ${row.position || ""} ${row.bitrix_user_id} ${row.account?.display_name || ""}`.toLowerCase();
    return hay.includes(state.q);
  }

  function renderRows() {
    const rows = state.rows.filter(matches);
    clear(tableHost);
    if (!rows.length) {
      tableHost.append(el("div.lai-acc__empty", {}, [state.rows.length ? "Nobody matches that search." : "No users to show."]));
      return;
    }
    tableHost.append(
      el("table.lai-acc__table", {}, [
        el("thead", {}, [
          el("tr", {}, [
            el("th", {}, ["Person"]),
            el("th", {}, ["Panel"]),
            el("th", {}, ["Handovers"]),
            ...FLAGS.map(([, label, title]) => el("th", { title }, [label])),
          ]),
        ]),
        el("tbody", {}, rows.map(renderRow)),
      ])
    );
  }

  function renderRow(row) {
    const locked = row.admin || row.bitrix_user_id === state.mine || (row.account && (!row.account.is_active || !row.account.can_official_api));
    const tags = [
      row.admin ? el("span.lai-acc__tag.lai-acc__tag--admin", { title: "A panel admin sees everything" }, ["admin: everything"]) : null,
      !row.in_bitrix ? el("span.lai-acc__tag", { title: "Not in the portal's active users today" }, ["not in Bitrix"]) : null,
      row.account && !row.account.is_active ? el("span.lai-acc__tag.lai-acc__tag--off", {}, ["inactive"]) : null,
    ].filter(Boolean);
    return el("tr", { "data-bitrix": row.bitrix_user_id }, [
      el("td", {}, [
        el("div.lai-acc__who", {}, [
          el("div.lai-acc__name", {}, [row.name, ...tags]),
          el("div.lai-acc__sub", {}, [[row.position, `Bitrix ${row.bitrix_user_id}`].filter(Boolean).join(" · ")]),
        ]),
      ]),
      el("td.lai-acc__sub", {}, [accountText(row)]),
      el("td.lai-acc__cell", {}, [String(row.handovers || 0)]),
      ...FLAGS.map(([flag]) => el("td.lai-acc__cell", {}, [renderSwitch(row, flag, locked)])),
    ]);
  }

  function renderSwitch(row, flag, locked) {
    const on = Boolean(row.admin ? true : row.access?.[flag]);
    const input = el("input", {
      type: "checkbox",
      checked: on,
      disabled: Boolean(locked) || state.busy.has(row.bitrix_user_id),
      "aria-label": `${FLAGS.find(([key]) => key === flag)[1]} for ${row.name}`,
      onchange: () => setFlag(row, flag, input.checked, input),
    });
    const hint = row.admin ? "admin" : row.bitrix_user_id === state.mine ? "you" : "";
    return el("label.lai-acc__switch", { title: locked ? "Cannot be changed here" : "" }, [input, hint ? el("span.lai-acc__sub", {}, [hint]) : null]);
  }

  async function setFlag(row, flag, value, input) {
    state.busy.add(row.bitrix_user_id);
    input.disabled = true;
    renderRows(); // the row's three switches disabled together: one change in flight per person, answers in order
    say(`Saving ${row.name}…`);
    try {
      const updated = await apiFetch(`/api/leadai/access/${encodeURIComponent(row.bitrix_user_id)}/`, { method: "PUT", body: { [flag]: value } });
      const index = state.rows.findIndex((item) => item.bitrix_user_id === row.bitrix_user_id);
      if (index !== -1 && updated && updated.bitrix_user_id) state.rows[index] = updated;
      say(`${row.name}: ${FLAGS.find(([key]) => key === flag)[1]} ${value ? "on" : "off"}.`);
    } catch (error) {
      say(`Could not change ${row.name}: ${error.message}`, true);
    } finally {
      state.busy.delete(row.bitrix_user_id);
      renderRows();
    }
  }
}
