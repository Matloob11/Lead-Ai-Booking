/**
 * Who works which linked phone, and how those phones are behaving.
 *
 * Two screens behind one dialog, because they answer the same question from
 * either end: an admin deciding who to put on a number wants to know what that
 * number is already carrying, and an admin looking at a number in trouble wants
 * to know who is on it.
 *
 * The rule the assignment screen enforces is the Cloud side's rule, deliberately:
 * an assignment is **ownership, not a filter**. An agent put on a phone sees
 * every conversation on it, not only the ones they answered — because the agent
 * gives that number to the customer themselves and a colleague covering for them
 * is normal. Nothing here narrows what an agent sees within a phone.
 *
 * Nothing a customer or an agent typed goes through innerHTML: agent names,
 * labels and phone numbers are all text nodes.
 */

import { icon, initials, hueFor } from "./icons.js";

/* --------------------------------------------------------------- plumbing */

function el(spec, props = {}, children = []) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");

  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      node.className = [node.className, value].filter(Boolean).join(" ");
    } else if (key in node && key !== "list") {
      node[key] = value;
    } else {
      node.setAttribute(key, value === true ? "" : value);
    }
  }

  for (const child of [children].flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const clear = (node) => (node.replaceChildren(), node);

/**
 * This service's own API, resolved against the page.
 *
 * nginx publishes wa-qr under /qr/, so "/api/sessions" written absolute would
 * leave for the host root and arrive at Django instead.
 */
const apiBase = new URL("./", document.baseURI);
const onApi = (path) => new URL(String(path).replace(/^\//, ""), apiBase).href;

async function api(path, { method = "GET", body } = {}) {
  const init = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(onApi(path), init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.error || payload?.detail || `${method} ${path} → HTTP ${response.status}`);
  }
  return payload;
}

/**
 * Django's API, which is **not** under /qr/.
 *
 * The one place a root-absolute path is right: the backend is the same origin
 * as this page — nginx serves Django at / and this panel at /qr/ — so the
 * admin's own session cookie authenticates the call and this service never
 * holds a credential for it. Putting it through onApi() would send it to wa-qr,
 * which has no idea who the agents are.
 */
const django = async (path) => {
  const response = await fetch(path, { headers: { Accept: "application/json" }, credentials: "same-origin" });
  if (!response.ok) throw new Error(`${path} → HTTP ${response.status}`);
  return response.json();
};

const asList = (payload, key) => {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const candidate of [key, "results", "items", "data"]) {
    if (candidate && Array.isArray(payload[candidate])) return payload[candidate];
  }
  return [];
};

const withPlus = (digits) => (digits ? `+${String(digits).replace(/\D/g, "")}` : "");

const phoneName = (s) =>
  s.label || withPlus(s.phone_number ?? s.phoneNumber) || `Phone #${s.id}`;

/** "4 minutes", "3 days" — how long since something last happened. */
function since(iso) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;

  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"}`;
  return `${Math.round(hours / 24)} days`;
}

const STATUS = {
  ready: { chip: "chip--ok", text: "Ready" },
  qr: { chip: "chip--warn", text: "Waiting for a scan" },
  authenticated: { chip: "chip--warn", text: "Connecting" },
  initialising: { chip: "chip--plain", text: "Starting" },
  disconnected: { chip: "chip--err", text: "Disconnected" },
  banned: { chip: "chip--err", text: "Banned" },
};
const statusOf = (value) => STATUS[value] || { chip: "chip--plain", text: value || "Unknown" };

const RISK = {
  high: { cls: "pa-risk--high", text: "At risk of a ban" },
  watch: { cls: "pa-risk--watch", text: "Worth watching" },
  ok: { cls: "pa-risk--ok", text: "Normal" },
};

/* ------------------------------------------------------------- the dialog */

/**
 * Opens the administration screen.
 *
 * @param {object} deps
 * @param {Function} deps.dialog      app.js's dialog(), because window.prompt
 *                                    and confirm() do nothing in this iframe
 * @param {Function} [deps.askConfirm]
 * @param {Function} [deps.onChanged] called when a roster was saved, so the
 *                                    panel behind can refetch what it may see
 */
export function openPhonesAdmin({ dialog, askConfirm, onChanged = () => {} }) {
  const body = el("div.dlg__body.pa", {}, [el("div.pa-loading", {}, ["Loading…"])]);

  const tabs = el("div.pa-tabs");
  const d = dialog({
    title: "Phones and agents",
    wide: true,
    body: el("div.dlg__body", {}, [tabs, body]),
  });

  const state = { tab: "agents", sessions: [], agents: [], agentsError: "", risk: [], counts: new Map() };

  const tab = (key, label, glyph) =>
    el(
      "button.pa-tab",
      {
        type: "button",
        class: state.tab === key ? "is-on" : "",
        onclick: () => {
          state.tab = key;
          paintTabs();
          paint();
        },
      },
      [icon(glyph, { size: 15 }), label]
    );

  function paintTabs() {
    clear(tabs).append(tab("agents", "Agents", "users"), tab("reports", "Reports", "chat"));
  }

  /* ------------------------------------------------------------- loading */

  async function load() {
    clear(body).append(el("div.pa-loading", {}, ["Loading…"]));

    const [sessions, risk] = await Promise.all([
      api("api/sessions").then((r) => asList(r, "sessions")).catch(() => []),
      api("api/risk").then((r) => asList(r, "risk")).catch(() => []),
    ]);

    state.sessions = sessions;
    state.risk = risk;

    // Names come from Django, which is the only place an agent exists. A
    // failure here is not fatal — the ids still work, and saying so beats an
    // empty screen with no explanation.
    try {
      state.agents = asList(await django("/api/catalog/agents/"), "agents");
      state.agentsError = "";
    } catch (error) {
      state.agents = [];
      state.agentsError =
        error.message.includes("403") || error.message.includes("401")
          ? "The agent list is admin-only and this session was refused it."
          : `The agent list could not be loaded: ${error.message}`;
    }

    // Conversation counts per phone, for the reports tab.
    state.counts = new Map();
    await Promise.all(
      sessions.map(async (session) => {
        try {
          const rows = asList(await api(`api/conversations?session_id=${session.id}&limit=100`), "conversations");
          const unread = rows.reduce((sum, row) => sum + Number(row.unread_count || 0), 0);
          const latest = rows
            .map((row) => row.last_message_at)
            .filter(Boolean)
            .sort()
            .at(-1);
          state.counts.set(Number(session.id), {
            chats: rows.length,
            // The route caps a page at 100. Saying "100+" is the difference
            // between a report and a wrong number.
            capped: rows.length >= 100,
            unread,
            latest,
          });
        } catch {
          state.counts.set(Number(session.id), null);
        }
      })
    );

    paint();
  }

  /* -------------------------------------------------------------- agents */

  const agentName = (id) => {
    const found = state.agents.find((a) => Number(a.id) === Number(id));
    return found?.display_name || found?.name || `Agent #${id}`;
  };

  function agentsTab() {
    if (!state.sessions.length) return noPhones();

    const wrap = el("div.pa-list");
    if (state.agentsError) wrap.append(el("div.pa-warn", {}, [icon("alert", { size: 15 }), state.agentsError]));

    for (const session of state.sessions) {
      // A local copy: the roster is only sent when Save is pressed, so a
      // half-made change never reaches the server.
      const roster = (session.agents || []).map((a) => ({ ...a }));
      const look = statusOf(session.status);
      const rows = el("div.pa-roster");
      const problem = el("div.pa-error", { hidden: true });
      const saveBtn = el("button.btn.btn--sm", { type: "button" }, ["Save"]);

      const paintRoster = () => {
        clear(rows);

        if (!roster.length) {
          rows.append(
            el("div.pa-none", {}, [
              "Nobody is assigned. Only administrators can see this phone's chats until somebody is.",
            ])
          );
        }

        for (const entry of roster) {
          const name = agentName(entry.agent_id);
          rows.append(
            el("div.pa-agent", {}, [
              el("div.avatar.avatar--sm", { style: `--hue: ${hueFor(String(entry.agent_id))}` }, [
                initials(name),
              ]),
              el("div.pa-agent__who", {}, [
                el("div.pa-agent__name", {}, [name]),
                el("div.pa-agent__id", {}, [`ID ${entry.agent_id}`]),
              ]),
              el(
                "select.pa-role",
                {
                  onchange: (event) => {
                    entry.role = event.target.value;
                    saveBtn.disabled = false;
                  },
                },
                ["primary", "backup"].map((role) =>
                  el("option", { value: role, selected: entry.role === role }, [
                    role === "primary" ? "Primary" : "Backup",
                  ])
                )
              ),
              el(
                "button.pa-x",
                {
                  type: "button",
                  title: `Remove ${name}`,
                  onclick: () => {
                    const at = roster.indexOf(entry);
                    if (at >= 0) roster.splice(at, 1);
                    saveBtn.disabled = false;
                    paintRoster();
                  },
                },
                [icon("close", { size: 14 })]
              ),
            ])
          );
        }

        // Whoever is not already on this phone.
        const spare = state.agents.filter((a) => !roster.some((r) => Number(r.agent_id) === Number(a.id)));
        const picker = el(
          "select.pa-add",
          {
            onchange: (event) => {
              const id = Number(event.target.value);
              event.target.value = "";
              if (!id) return;
              roster.push({ agent_id: id, role: "primary" });
              saveBtn.disabled = false;
              paintRoster();
            },
          },
          [
            el("option", { value: "" }, [spare.length ? "Add an agent…" : "Everyone is already on this phone"]),
            ...spare.map((a) =>
              el("option", { value: String(a.id) }, [a.display_name || a.name || `Agent #${a.id}`])
            ),
          ]
        );
        picker.disabled = !spare.length;

        rows.append(el("div.pa-addrow", {}, [picker]));
      };

      saveBtn.disabled = true;
      saveBtn.addEventListener("click", async () => {
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving…";
        problem.hidden = true;
        try {
          // The whole roster, not the difference — the route replaces what is
          // there, which is what lets this screen send the state it wants.
          const saved = await api(`api/sessions/${session.id}/agents`, {
            method: "PUT",
            body: { agents: roster.map((r) => ({ agent_id: r.agent_id, role: r.role })) },
          });
          session.agents = saved?.agents || roster;
          saveBtn.textContent = "Saved";
          onChanged();
          setTimeout(() => (saveBtn.textContent = "Save"), 1400);
        } catch (error) {
          saveBtn.disabled = false;
          saveBtn.textContent = "Save";
          problem.hidden = false;
          clear(problem).append(error.message);
        }
      });

      paintRoster();

      wrap.append(
        el("div.pa-card", {}, [
          el("div.pa-card__top", {}, [
            el("div", {}, [
              el("div.pa-card__name", {}, [phoneName(session)]),
              session.label && (session.phone_number ?? session.phoneNumber)
                ? el("div.pa-card__sub", {}, [withPlus(session.phone_number ?? session.phoneNumber)])
                : null,
            ]),
            el("span.chip", { class: look.chip }, [look.text]),
          ]),
          rows,
          problem,
          el("div.pa-card__foot", {}, [
            el("span.pa-hint", {}, ["An agent assigned here sees every chat on this phone."]),
            saveBtn,
          ]),
        ])
      );
    }

    return wrap;
  }

  /* ------------------------------------------------------------- reports */

  function reportsTab() {
    if (!state.sessions.length) return noPhones();

    const wrap = el("div.pa-list");
    wrap.append(
      el("p.dlg__text", {}, [
        "Counted from what these phones have actually done. Behaviour is measured on when a ",
        "message was sent, not when it was imported — so a phone linked today with months of ",
        "history is not read as a brand-new number.",
      ])
    );

    for (const session of state.sessions) {
      const id = Number(session.id);
      const look = statusOf(session.status);
      const counts = state.counts.get(id);
      const risk = state.risk.find((r) => Number(r.session_id) === id);
      const level = RISK[risk?.level] || RISK.ok;
      const quiet = counts?.latest ? since(counts.latest) : null;

      const stat = (value, label) =>
        el("div.pa-stat", {}, [el("div.pa-stat__n", {}, [value]), el("div.pa-stat__l", {}, [label])]);

      wrap.append(
        el("div.pa-card", {}, [
          el("div.pa-card__top", {}, [
            el("div", {}, [
              el("div.pa-card__name", {}, [phoneName(session)]),
              el("div.pa-card__sub", {}, [
                (session.agents || []).length
                  ? (session.agents || []).map((a) => agentName(a.agent_id)).join(", ")
                  : "No agent assigned",
              ]),
            ]),
            el("span.chip", { class: look.chip }, [look.text]),
          ]),

          el("div.pa-stats", {}, [
            stat(counts ? `${counts.chats}${counts.capped ? "+" : ""}` : "—", "chats"),
            stat(counts ? String(counts.unread) : "—", "unread"),
            stat(quiet || "—", quiet ? "since the last message" : "no messages yet"),
            stat(String(risk?.signals?.outbound24h ?? "—"), "sent in 24h"),
            stat(String(risk?.signals?.newContacts24h ?? "—"), "new contacts in 24h"),
          ]),

          counts?.capped
            ? el("div.pa-note", {}, [
                "Only the first 100 chats were counted — the list route pages at 100.",
              ])
            : null,

          el("div.pa-risk", { class: level.cls }, [
            el("div.pa-risk__head", {}, [icon(risk?.level === "ok" ? "check" : "alert", { size: 15 }), level.text]),
            ...(risk?.reasons?.length
              ? risk.reasons.map((reason) => el("div.pa-risk__why", {}, [reason]))
              : [el("div.pa-risk__why", {}, ["Nothing in this phone's recent behaviour looks like the behaviour WhatsApp bans numbers for."])]),
          ]),

          // The history import, when there is one worth naming.
          session.history && session.history.status !== "done"
            ? el("div.pa-note", {}, [historyLine(session)])
            : null,

          session.last_error || session.lastError
            ? el("div.pa-error", {}, [session.last_error || session.lastError])
            : null,
        ])
      );
    }

    return wrap;
  }

  /** What the import is doing, in a sentence. */
  function historyLine(session) {
    const h = session.history || {};
    const done = h.chatsDone ?? 0;
    const total = h.chatsTotal ?? 0;

    if (h.status === "running") {
      return total ? `Importing history — ${done} of ${total} chats read.` : "Importing history…";
    }
    if (h.status === "failed") return `The history import stopped: ${h.error || "no reason recorded"}.`;
    if (session.status === "disconnected") {
      return "The import is paused while this phone is disconnected. It resumes when the phone reconnects.";
    }
    return "History has not been imported yet.";
  }

  /* -------------------------------------------------------- empty states */

  function noPhones() {
    return el("div.pa-empty", {}, [
      el("div.pa-empty__art", {}, [icon("phone", { size: 26 })]),
      el("div.pa-empty__title", {}, ["No phone is linked"]),
      el("div.pa-empty__note", {}, [
        "Nothing can be assigned or measured until a phone is linked. Close this and use ",
        "“Link a phone” to scan a QR code with the handset you want to connect.",
      ]),
    ]);
  }

  function paint() {
    clear(body).append(state.tab === "agents" ? agentsTab() : reportsTab());
  }

  paintTabs();
  load().catch((error) => {
    clear(body).append(el("div.alert", {}, [`This screen could not load: ${error.message}`]));
  });

  return d;
}

/* ------------------------------------------------------- the panel's gaps */

/**
 * Says why the panel is empty, when it is.
 *
 * Installed on import rather than called, so app.js carries one line for both
 * halves of this module. It owns the element it adds and touches nothing that
 * another module drew.
 *
 * Three silences worth breaking, and the middle one is the reason this exists:
 * an agent with no phone assigned gets an empty list from the API and a panel
 * that says "No chats yet" — which reads as "no customer has written", when what
 * happened is that nobody gave them a number to answer on.
 */
function installPanelStates() {
  let notice = null;

  const check = async () => {
    const side = document.querySelector(".side");
    if (!side) return;

    const [me, sessions] = await Promise.all([
      api("api/me").catch(() => null),
      api("api/sessions").then((r) => asList(r, "sessions")).catch(() => null),
    ]);
    if (!me || sessions === null) return;

    const message = verdict(me, sessions);
    if (!message) {
      notice?.remove();
      notice = null;
      return;
    }

    const next = el("div.pa-state", {}, [
      el("div.pa-state__art", {}, [icon(message.glyph, { size: 20 })]),
      el("div", {}, [
        el("div.pa-state__title", {}, [message.title]),
        el("div.pa-state__note", {}, [message.note]),
      ]),
    ]);

    if (notice) notice.replaceWith(next);
    else side.insertBefore(next, side.querySelector(".convs"));
    notice = next;
  };

  /** @returns {{glyph: string, title: string, note: string}|null} */
  function verdict(me, sessions) {
    if (!sessions.length) {
      return me.is_admin
        ? {
            glyph: "phone",
            title: "No phone is linked",
            note: "Open Manage and link a phone by scanning its QR code. Chats appear once one is connected.",
          }
        : {
            glyph: "phone",
            title: "No phone is assigned to you",
            note: "An administrator has to put you on a linked phone before its chats reach you. Ask for one to be assigned.",
          };
    }

    const dead = sessions.filter((s) => s.status === "disconnected" || s.status === "banned");
    if (dead.length === sessions.length) {
      const one = dead.length === 1;
      return {
        glyph: "alert",
        title: one ? `${phoneName(dead[0])} is ${statusOf(dead[0].status).text.toLowerCase()}` : "Every phone is offline",
        note: dead.some((s) => s.status === "banned")
          ? "A banned number cannot be recovered. Existing chats stay readable; nothing new will arrive or send."
          : "Chats already imported stay readable, but nothing new arrives until the phone reconnects. Open Manage to scan again.",
      };
    }

    return null;
  }

  // Once the panel has built itself, and then rarely: the answer changes when an
  // admin assigns a phone, which is not something that happens twice a minute.
  const start = () => {
    check();
    setInterval(check, 60_000);
  };

  if (document.querySelector(".side")) start();
  else {
    const observer = new MutationObserver(() => {
      if (!document.querySelector(".side")) return;
      observer.disconnect();
      start();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
}

installPanelStates();
