/**
 * Agent-centric Official API roster: one row per agent, every number they hold.
 *
 * A plain table for the Numbers Management By agent tab.
 */

import { el, clear, debounce } from "../core/dom.js";

const NOTE_KEY = "a7.agentNumbers.notes.v1";

function readNotes() {
  try {
    const raw = JSON.parse(localStorage.getItem(NOTE_KEY) || "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

function writeNote(agentId, text) {
  const all = readNotes();
  const key = String(agentId);
  const next = String(text || "");
  if (next) all[key] = next;
  else delete all[key];
  try {
    localStorage.setItem(NOTE_KEY, JSON.stringify(all));
  } catch {
    /* private mode — keep typing, just cannot persist */
  }
}

export function filterAgents(agents, query, numbers) {
  const q = String(query || "").trim().toLowerCase();
  const list = [...(agents || [])].sort((a, b) =>
    String(a.display_name || "").localeCompare(String(b.display_name || ""), undefined, {
      sensitivity: "base",
    })
  );
  if (!q) return list;
  const byId = new Map((numbers || []).map((n) => [n.id, n]));
  return list.filter((agent) => {
    const name = String(agent.display_name || "").toLowerCase();
    const community = String(agent.community || "").toLowerCase();
    const username = String(agent.username || "").toLowerCase();
    if (name.includes(q) || community.includes(q) || username.includes(q)) return true;
    return (agent.numbers || []).some((ref) => {
      const full = byId.get(ref.id);
      const account = String(full?.account_username || "").toLowerCase();
      const phone = String(full?.phone_number || ref.phone_number || "").toLowerCase();
      return (account && account.includes(q)) || (phone && phone.includes(q));
    });
  });
}

export function resolveAgentNumbers(agent, numbers) {
  const byId = new Map((numbers || []).map((n) => [n.id, n]));
  return (agent.numbers || [])
    .map((ref) => {
      const full = byId.get(ref.id);
      return {
        id: ref.id,
        phone_number: full?.phone_number || ref.phone_number || "",
        title: full?.title || full?.label || ref.phone_number || "",
        label: full?.label || "",
        community: full?.community || "",
        waba_business_id: full?.waba_business_id || "",
        account_username: full?.account_username || "",
        role: ref.role || "primary",
      };
    })
    .sort((a, b) => String(a.phone_number).localeCompare(String(b.phone_number)));
}

function noteBox(agentId) {
  const box = el("textarea.an-note", {
    rows: 3,
    placeholder: "Write a note…",
    spellcheck: false,
  });
  box.value = readNotes()[String(agentId)] || "";
  const persist = debounce(() => writeNote(agentId, box.value), 200);
  box.addEventListener("input", persist);
  box.addEventListener("blur", () => writeNote(agentId, box.value));
  return box;
}

function agentCell(name, count) {
  return el("td.an-agent", { rowspan: String(Math.max(count, 1)) }, [
    el("div.an-agent__name", {}, [name]),
    el("div.an-agent__count", {}, [
      count ? `${count} number${count === 1 ? "" : "s"}` : "No numbers",
    ]),
  ]);
}

function numberCell(n) {
  const phone = n.phone_number || "—";
  const account = String(n.account_username || "").trim();
  const label = String(n.label || n.title || "").trim();
  return el("td", {}, [
    el("div", {}, [account ? `${phone} · ${account}` : phone]),
    label && label !== phone ? el("div.an-sub", {}, [label]) : null,
  ]);
}

export function renderAgentLookup(target, { agents, numbers, query }) {
  clear(target);
  const q = String(query || "").trim();
  const matches = filterAgents(agents, query, numbers);
  const rows = [];

  for (const agent of matches) {
    const held = resolveAgentNumbers(agent, numbers);
    const name = String(agent.display_name || `Agent ${agent.id}`).trim();
    if (!held.length) {
      if (!q) continue;
      rows.push(
        el("tr", {}, [
          agentCell(name, 0),
          el("td", {}, ["—"]),
          el("td", {}, ["—"]),
          el("td.an-notecol", {}, [noteBox(agent.id)]),
        ])
      );
      continue;
    }

    held.forEach((n, index) => {
      const cells = [];
      if (index === 0) cells.push(agentCell(name, held.length));
      cells.push(numberCell(n));
      cells.push(el("td", {}, [n.account_username || "—"]));
      if (index === 0) cells.push(el("td.an-notecol", { rowspan: String(held.length) }, [noteBox(agent.id)]));
      rows.push(el("tr", {}, cells));
    });
  }

  if (!rows.length) {
    target.append(
      el("p.an-empty", {}, [q ? "No agent matches that name." : "No Official API numbers assigned."])
    );
    return;
  }

  target.append(
    el("table.an-table", {}, [
      el("thead", {}, [
        el("tr", {}, [
          el("th", {}, ["Agent"]),
          el("th", {}, ["Numbers"]),
          el("th", {}, ["Username"]),
          el("th", {}, ["Note"]),
        ]),
      ]),
      el("tbody", {}, rows),
    ])
  );
}

export function mountAgentLookup(host, { agents, numbers, autofocus = false } = {}) {
  const search = el("input.an-search", {
    type: "text",
    placeholder: "Type an agent name…",
    autocomplete: "off",
    spellcheck: false,
  });
  const results = el("div.an-results");
  const paint = () => renderAgentLookup(results, { agents, numbers, query: search.value });
  search.addEventListener("input", debounce(paint, 120));
  clear(host).append(search, results);
  paint();
  if (autofocus) search.focus();
  return {
    search,
    refresh(next = {}) {
      if (next.agents) agents = next.agents;
      if (next.numbers) numbers = next.numbers;
      paint();
    },
  };
}
