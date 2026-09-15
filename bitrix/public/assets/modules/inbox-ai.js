/**
 * AI desk — self-mounts. Does not import inbox.js; other sessions edit that file.
 *
 * Per-chat: an AI button in the thread header, context form, optional pause.
 * Global: Inbox tools → AI desk, with new / all / selected coverage.
 */
import { el, clear, debounce, modal, toast } from "../core/dom.js";
import { auth, inboxAi, asList } from "../api/api.js";

let activeConversationId = null;
let mounted = false;
let me = null;

function spark(size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.classList.add("icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute(
    "d",
    "M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"
  );
  svg.appendChild(path);
  return svg;
}

function isAdmin() {
  if (me?.is_wa_admin) return true;
  return [...document.querySelectorAll(".sidebar__menu .menu__section")].some(
    (node) => (node.textContent || "").trim() === "Admin"
  );
}

function pulse(size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.classList.add("icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute(
    "d",
    "M19.5 13.5 12 21l-7.5-7.5a5 5 0 1 1 7.5-6.55 5 5 0 1 1 7.5 6.55z"
  );
  svg.appendChild(path);
  return svg;
}

function watchConversationFetches() {
  if (window.__iaiFetchPatched) return;
  window.__iaiFetchPatched = true;
  const orig = window.fetch.bind(window);
  window.fetch = function patchedFetch(input, init) {
    try {
      const url = typeof input === "string" ? input : input && input.url;
      const match = String(url || "").match(/\/api\/inbox\/conversations\/(\d+)\//);
      if (match) {
        const next = Number(match[1]);
        if (next && next !== activeConversationId) {
          activeConversationId = next;
          queueMicrotask(paintThreadButton);
        }
      }
    } catch {
      /* never block inbox traffic */
    }
    return orig(input, init);
  };
}

function injectMenu() {
  const menu = document.querySelector(".sidebar__menu");
  if (!menu) return false;

  let item = menu.querySelector("#iai-menu-item");
  if (!item) {
    item = el(
      "button.btn.menu__item",
      { id: "iai-menu-item", type: "button", onclick: () => openDesk() },
      [spark(16), "AI desk"]
    );
    const sections = [...menu.querySelectorAll(".menu__section")];
    const tools = sections.find((node) => (node.textContent || "").trim() === "Inbox tools");
    if (tools) {
      let last = tools;
      let next = tools.nextElementSibling;
      while (next && !next.classList.contains("menu__section")) {
        last = next;
        next = next.nextElementSibling;
      }
      last.after(item);
    } else {
      menu.append(item);
    }
  }

  injectHealthMenu(menu);
  return true;
}

function lastMenuItemInSection(section) {
  let last = section;
  let next = section.nextElementSibling;
  while (next && !next.classList.contains("menu__section")) {
    last = next;
    next = next.nextElementSibling;
  }
  return last;
}

function injectHealthMenu(menu) {
  // Inbox.js only draws the Admin section for wa admins. Mirror that —
  // do not wait for /api/auth/me, which used to leave this item missing.
  const admin = [...menu.querySelectorAll(".menu__section")].find(
    (node) => (node.textContent || "").trim() === "Admin"
  );
  let health = menu.querySelector("#iai-health-item");
  if (!admin) {
    health?.remove();
    return;
  }
  if (!health) {
    health = el(
      "button.btn.menu__item",
      { id: "iai-health-item", type: "button", onclick: () => openHealth() },
      [pulse(16), "Conversation Health"]
    );
  }
  const last = lastMenuItemInSection(admin);
  if (last !== health) last.after(health);
}

function dots(size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "currentColor");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  [
    [12, 5],
    [12, 12],
    [12, 19],
  ].forEach(([cx, cy]) => {
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", String(cx));
    c.setAttribute("cy", String(cy));
    c.setAttribute("r", "1.7");
    svg.appendChild(c);
  });
  return svg;
}

function glassSheet(dialog) {
  dialog.box.classList.add("iai-modal");
  dialog.box.parentElement?.classList.add("iai-scrim");
}

function menuOf(wrap) {
  return wrap?._iaiMenu || wrap?.querySelector(".iai-more__menu") || null;
}

function parkMenu(wrap) {
  const menu = menuOf(wrap);
  if (!menu) return;
  menu.classList.remove("iai-more__menu--open");
  menu.style.top = "";
  menu.style.left = "";
  menu.style.right = "";
  menu.style.maxHeight = "";
  if (wrap?.isConnected) wrap.append(menu);
  else menu.remove();
}

function closeActionMenus() {
  document.querySelectorAll(".iai-more--open").forEach((wrap) => {
    wrap.classList.remove("iai-more--open");
    wrap.querySelector(".iai-more__btn")?.setAttribute("aria-expanded", "false");
    parkMenu(wrap);
  });
  document.querySelectorAll("body > .iai-more__menu").forEach((menu) => {
    const home = menu._iaiHome;
    if (home?.isConnected) {
      home.classList.remove("iai-more--open");
      home.querySelector(".iai-more__btn")?.setAttribute("aria-expanded", "false");
      parkMenu(home);
    } else {
      menu.remove();
    }
  });
}

function placeOpenMenu(btn, menu) {
  const frame = window.visualViewport;
  const viewW = Math.floor(frame?.width || window.innerWidth || 0);
  const viewH = Math.floor(frame?.height || window.innerHeight || 0);
  const rect = btn.getBoundingClientRect();
  const width = Math.min(240, Math.max(200, viewW - 16));
  menu.style.minWidth = "200px";
  menu.style.maxWidth = `${Math.min(240, viewW - 16)}px`;
  let left = rect.right - width;
  if (left < 8) left = 8;
  if (left + 200 > viewW - 8) left = Math.max(8, viewW - 208);
  let top = rect.bottom + 6;
  const roomBelow = viewH - top - 8;
  if (roomBelow < 120 && rect.top > 160) {
    const height = Math.min(360, rect.top - 14);
    top = Math.max(8, rect.top - height - 6);
    menu.style.maxHeight = `${height}px`;
  } else {
    menu.style.maxHeight = `${Math.min(360, Math.max(120, roomBelow))}px`;
  }
  menu.style.position = "fixed";
  menu.style.top = `${Math.round(top)}px`;
  menu.style.left = `${Math.round(left)}px`;
  menu.style.right = "auto";
  menu.style.zIndex = "120";
}

function openActionMenu(wrap, btn) {
  const menu = menuOf(wrap);
  if (!menu) return;
  wrap.classList.add("iai-more--open");
  btn.setAttribute("aria-expanded", "true");
  menu.classList.add("iai-more__menu--open");
  document.body.append(menu);
  placeOpenMenu(btn, menu);
}

function actionMenuHost(tools) {
  let wrap = tools.querySelector(":scope > .iai-more");
  if (wrap) return wrap;

  const btn = el("button.btn.btn--ghost.btn--sm.iai-more__btn", {
    type: "button",
    title: "Chat actions",
    "aria-haspopup": "true",
    "aria-expanded": "false",
  }, [dots(16)]);
  const menu = el("div.iai-more__menu", { role: "menu" });
  wrap = el("div.iai-more", {}, [btn, menu]);
  wrap._iaiMenu = menu;
  menu._iaiHome = wrap;

  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const willOpen = !wrap.classList.contains("iai-more--open");
    closeActionMenus();
    if (willOpen) openActionMenu(wrap, btn);
  });
  menu.addEventListener("click", () => closeActionMenus());
  tools.append(wrap);
  return wrap;
}

function foldThreadActions() {
  const tools = document.querySelector(".thread__tools");
  if (!tools) {
    closeActionMenus();
    return;
  }

  const strays = [...tools.children].filter((node) => {
    if (node.classList.contains("iai-more")) return false;
    if (node.classList.contains("pill")) return false;
    return node.matches("button") || node.classList.contains("btn");
  });
  if (!strays.length) {
    const wrap = tools.querySelector(":scope > .iai-more");
    if (!wrap) closeActionMenus();
    else wrap.hidden = !menuOf(wrap)?.childElementCount;
    return;
  }

  const wrap = actionMenuHost(tools);
  const menu = menuOf(wrap);
  if (!menu) return;
  strays.forEach((node) => {
    node.classList.add("iai-more__item");
    node.setAttribute("role", "menuitem");
    menu.append(node);
  });
  wrap.hidden = !menu.childElementCount;
}

function paintThreadButton() {
  const tools = document.querySelector(".thread__tools");
  if (!tools) return;
  const wrap = tools.querySelector(":scope > .iai-more");
  const existing =
    tools.querySelector(".iai-thread-btn") ||
    menuOf(wrap)?.querySelector(".iai-thread-btn") ||
    document.querySelector("body > .iai-more__menu .iai-thread-btn");
  if (!activeConversationId) {
    if (existing) existing.remove();
    foldThreadActions();
    return;
  }
  if (existing) {
    if (existing.dataset.conversationId !== String(activeConversationId)) {
      existing.dataset.conversationId = String(activeConversationId);
      refreshThreadButton(existing);
    }
    foldThreadActions();
    return;
  }

  const btn = el(
    "button.btn.btn--ghost.btn--sm.iai-thread-btn",
    {
      type: "button",
      title: "Let AI cover this chat",
      onclick: () => openCover(Number(btn.dataset.conversationId)),
    },
    [spark(14), " AI"]
  );
  btn.dataset.conversationId = String(activeConversationId);
  tools.prepend(btn);
  refreshThreadButton(btn);
  foldThreadActions();
}

async function refreshThreadButton(btn) {
  const id = Number(btn.dataset.conversationId);
  if (!id) return;
  try {
    const data = await inboxAi.cover(id);
    const on = Boolean(data.enabled) && !data.paused_at;
    const paused = Boolean(data.enabled && data.paused_at);
    btn.classList.toggle("iai-thread-btn--on", on);
    btn.classList.toggle("iai-thread-btn--paused", paused);
    btn.title = paused
      ? "AI paused — you replied in this chat"
      : on
        ? "AI is covering this chat"
        : "Let AI cover this chat";
  } catch {
    /* button still opens the form */
  }
}

function observeThread() {
  const root = document.getElementById("root") || document.body;
  const observer = new MutationObserver(() => {
    paintThreadButton();
    injectMenu();
  });
  observer.observe(root, { childList: true, subtree: true });
}

document.addEventListener("click", closeActionMenus);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeActionMenus();
});
document.addEventListener(
  "scroll",
  (event) => {
    if (event.target?.closest?.(".iai-more__menu")) return;
    if (document.querySelector(".iai-more__menu--open")) closeActionMenus();
  },
  true
);
window.visualViewport?.addEventListener("resize", closeActionMenus);

function scopeCard(id, label, hint, current, onPick) {
  const selected = current === id;
  return el(
    "button.iai-scope",
    {
      type: "button",
      class: selected ? "iai-scope--on" : "",
      onclick: () => onPick(id),
    },
    [
      el("strong.iai-scope__name", {}, [label]),
      el("span.iai-scope__hint", {}, [hint]),
    ]
  );
}

function contextField(value, placeholder) {
  return el("textarea.iai-field.iai-field--area", {
    rows: 7,
    maxlength: 8000,
    placeholder,
    value: value || "",
  });
}

function contactLabel(row) {
  return row.name || row.wa_id || `Chat #${row.id}`;
}

const HEALTH_COLOURS = ["red", "pink", "yellow", "white", "green"];
const HEALTH_LABEL = {
  red: "Red",
  pink: "Pink",
  yellow: "Amber",
  white: "Hot",
  green: "Green",
};
const HEALTH_MEANING = {
  red: "Integrity risk — deal may be moving outside the company",
  pink: "Client issue — abuse, threats, or aggressive complaints",
  yellow: "Agent cannot satisfy — budget / area / capability gap",
  white: "Hot deal — interest + closing discussion",
  green: "Clean / normal — no problems",
};

function openChatFromHealth(conversationId, closeDialog) {
  closeDialog?.();
  if (typeof window.a7wa?.openConversation === "function") {
    window.a7wa.openConversation(conversationId);
  }
}

function healthRowTitle(row) {
  return row.name || row.wa_id || `Chat #${row.conversation_id}`;
}

function paintHealth(host, { onOpenChat } = {}) {
  let activeColour = null;
  const note = el("p.iai-h-note");

  const render = async () => {
    clear(host);
    if (!isAdmin()) return;
    host.append(el("p.iai-h-lead", {}, ["AI reads Official chats and bins them with the same rules as Linked phones."]));

    if (activeColour) {
      const toolbar = el("div.iai-h-toolbar");
      toolbar.append(
        el("button.btn.btn--ghost.btn--sm", {
          type: "button",
          onclick: () => {
            activeColour = null;
            render();
          },
        }, ["Back"]),
        el("div.iai-h-heading", {}, [
          el("span.iai-h-dot", { class: `iai-h-dot--${activeColour}` }),
          el("strong", {}, [HEALTH_LABEL[activeColour]]),
        ])
      );
      host.append(toolbar, el("p.iai-h-hint", {}, [HEALTH_MEANING[activeColour]]));
      if (activeColour === "red") {
        host.append(
          el("p.iai-h-hint.iai-h-hint--warn", {}, [
            "Red is an integrity flag. Allow as green only after you have checked the chat. That lock stops AI flipping it back.",
          ])
        );
      }
      const list = el("div.iai-h-list", {}, [el("p.iai-muted", {}, ["Loading…"])]);
      host.append(list);
      try {
        const rows = await inboxAi.healthList(activeColour);
        clear(list);
        if (!rows.length) {
          list.append(el("p.iai-muted", {}, ["No chats in this colour yet."]));
          return;
        }
        rows.forEach((row) => {
          const title = healthRowTitle(row);
          const actions = el("div.iai-h-row__actions");
          if (activeColour === "red") {
            actions.append(
              el("button.btn.btn--ghost.btn--sm", {
                type: "button",
                onclick: () => askAllowGreen(row, render),
              }, ["Allow as green"])
            );
          }
          actions.append(
            el("button.btn.btn--primary.btn--sm", {
              type: "button",
              onclick: () => onOpenChat?.(row.conversation_id),
            }, ["Open chat"])
          );
          list.append(
            el("article.iai-h-row", {}, [
              el("div.iai-h-row__meta", {}, [
                el("strong", {}, [title]),
                el("span", {}, [[row.number, row.wa_id].filter(Boolean).join(" · ")]),
                row.reason ? el("span.iai-h-reason", {}, [row.reason]) : null,
              ]),
              actions,
            ])
          );
        });
      } catch (error) {
        clear(list);
        list.append(el("p.iai-muted", {}, [error?.message || "Could not load this colour."]));
      }
      return;
    }

    const tools = el("div.iai-h-toolbar");
    const analyseBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["Analyse chats"]);
    const reclassBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["Re-check false red"]);
    analyseBtn.addEventListener("click", async () => {
      analyseBtn.disabled = true;
      try {
        const res = await inboxAi.healthAnalyse();
        if (!res.enabled) toast("OpenAI is not configured", "err");
        else toast(res.enqueued ? `Queued ${res.enqueued} chats` : "Nothing left to analyse");
        render();
      } catch (error) {
        toast(error?.message || "Analyse failed", "err");
        analyseBtn.disabled = false;
      }
    });
    reclassBtn.addEventListener("click", async () => {
      reclassBtn.disabled = true;
      try {
        const res = await inboxAi.healthReclassifyFalseRed();
        if (!res.enabled) toast("OpenAI is not configured", "err");
        else if (!res.candidates) toast("No unlocked red chats");
        else toast(`Re-checking ${res.enqueued} red chats`);
        render();
      } catch (error) {
        toast(error?.message || "Re-check failed", "err");
        reclassBtn.disabled = false;
      }
    });
    tools.append(analyseBtn, reclassBtn);
    host.append(tools);

    const legend = el("ul.iai-h-legend");
    HEALTH_COLOURS.forEach((colour) => {
      legend.append(
        el("li", {}, [
          el("span.iai-h-dot", { class: `iai-h-dot--${colour}` }),
          el("span", {}, [el("strong", {}, [HEALTH_LABEL[colour]]), ` — ${HEALTH_MEANING[colour]}`]),
        ])
      );
    });
    host.append(legend);

    const grid = el("div.iai-h-grid", {}, [el("p.iai-muted", {}, ["Loading counts…"])]);
    host.append(grid, note);
    try {
      const summary = await inboxAi.healthSummary();
      clear(grid);
      HEALTH_COLOURS.forEach((colour) => {
        grid.append(
          el(
            "button.iai-h-card",
            {
              type: "button",
              class: `iai-h-card--${colour}`,
              title: HEALTH_MEANING[colour],
              onclick: () => {
                activeColour = colour;
                render();
              },
            },
            [
              el("span.iai-h-card__top", {}, [
                el("span.iai-h-dot", { class: `iai-h-dot--${colour}` }),
                el("span", {}, [HEALTH_LABEL[colour]]),
              ]),
              el("span.iai-h-card__value", {}, [String(summary[colour] ?? 0)]),
            ]
          )
        );
      });
      clear(note);
      note.append(
        `${summary.total || 0} chats scored` +
          (summary.unclassified ? `, ${summary.unclassified} still waiting` : "") +
          ". Analyse chats to score ones AI has not seen yet."
      );
    } catch (error) {
      clear(grid);
      grid.append(el("p.iai-muted", {}, [error?.message || "Could not load Conversation Health."]));
    }
  };

  render();
}

function askAllowGreen(row, onDone) {
  const password = el("input.iai-field", {
    type: "password",
    autocomplete: "current-password",
    placeholder: "Admin password",
  });
  const err = el("p.iai-h-error");
  const saveBtn = el("button.btn.btn--primary.iai-save", { type: "button" }, ["Confirm allow"]);
  const dialog = modal(
    "Allow as green",
    el("div.modal__body.iai", {}, [
      el("p.iai-lead", {}, [
        `Move ${healthRowTitle(row)} from Red to Green. AI will not change this colour again.`,
      ]),
      password,
      err,
      el("div.iai-actions", {}, [saveBtn]),
    ])
  );
  glassSheet(dialog);
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    clear(err);
    try {
      await inboxAi.healthAllowGreen(row.conversation_id, password.value);
      toast("Chat marked green");
      dialog.close();
      onDone?.();
    } catch (error) {
      err.append(error?.message || "Could not allow this chat");
      saveBtn.disabled = false;
    }
  });
}

function openHealth() {
  if (!isAdmin()) {
    toast("Conversation Health is admin only", "err");
    return;
  }
  const host = el("div.iai-health");
  const dialog = modal(
    "Conversation Health",
    el("div.modal__body.iai", {}, [host]),
    { wide: true }
  );
  glassSheet(dialog);
  dialog.box.classList.add("iai-modal--health");
  paintHealth(host, {
    onOpenChat: (id) => openChatFromHealth(id, dialog.close),
  });
}

async function openDesk() {
  let desk;
  try {
    desk = await inboxAi.desk();
  } catch (error) {
    toast(error?.message || "Could not load AI desk", "err");
    return;
  }

  const enabled = el("input", { type: "checkbox", checked: Boolean(desk.enabled) });
  let scope = desk.scope && desk.scope !== "off" ? desk.scope : "new";
  const context = contextField(
    desk.context,
    "How AI should talk on every chat it covers. Example: You are covering for Sarah. Be brief. We sell Mudon Al Ranim villas. Do not quote prices."
  );
  const selected = new Map((desk.selected || []).map((row) => [row.id, row]));
  const scopeHost = el("div.iai-scopes");
  const pickerHost = el("div.iai-picker");
  const note = el("p.iai-note");
  const saveBtn = el("button.btn.btn--primary.iai-save", { type: "button" }, ["Save AI desk"]);

  const paintNote = () => {
    clear(note);
    if (!desk.openai_configured) {
      note.append("OpenAI is not configured on the server, so AI cannot send yet. Saving still stores your instructions.");
      return;
    }
    note.append(
      "AI answers after the customer writes (24-hour window open). A message you type yourself pauses that chat until you hand it back from the chat’s AI button."
    );
  };

  const paintPicker = () => {
    pickerHost.hidden = scope !== "selected";
    if (scope !== "selected") return;
    clear(pickerHost);
    const chips = el("div.iai-chips");
    if (!selected.size) {
      chips.append(el("p.iai-muted", {}, ["No chats selected yet."]));
    } else {
      for (const row of selected.values()) {
        chips.append(
          el("button.iai-chip", {
            type: "button",
            title: "Remove",
            onclick: () => {
              selected.delete(row.id);
              paintPicker();
            },
          }, [contactLabel(row), " ×"])
        );
      }
    }
    const search = el("input.iai-field", {
      type: "search",
      placeholder: "Search chats to add",
    });
    const hits = el("div.iai-hits");
    const runSearch = debounce(async () => {
      clear(hits);
      try {
        const payload = await inboxAi.candidates(search.value.trim());
        const rows = asList(payload, "results");
        if (!rows.length) {
          hits.append(el("p.iai-muted", {}, ["No matching chats."]));
          return;
        }
        rows.forEach((row) => {
          const on = selected.has(row.id);
          hits.append(
            el(
              "button.iai-hit",
              {
                type: "button",
                class: on ? "iai-hit--on" : "",
                onclick: () => {
                  if (selected.has(row.id)) selected.delete(row.id);
                  else selected.set(row.id, row);
                  paintPicker();
                },
              },
              [
                el("span.iai-hit__name", {}, [contactLabel(row)]),
                el("span.iai-hit__meta", {}, [row.wa_id || row.preview || ""]),
              ]
            )
          );
        });
      } catch (error) {
        hits.append(el("p.iai-muted", {}, [error?.message || "Search failed."]));
      }
    }, 250);
    search.addEventListener("input", runSearch);
    pickerHost.append(
      el("h3.iai-sub", {}, ["Chats AI should cover"]),
      chips,
      search,
      hits
    );
    runSearch();
  };

  const paintScopes = () => {
    clear(scopeHost);
    [
      ["new", "New chats", "Only chats nobody on our side has answered yet."],
      ["all", "All my chats", "Every Official chat on the numbers assigned to you."],
      ["selected", "Selected chats", "Only the chats you pick below."],
    ].forEach(([id, label, hint]) => {
      scopeHost.append(scopeCard(id, label, hint, scope, (next) => {
        scope = next;
        paintScopes();
        paintPicker();
      }));
    });
  };

  paintNote();
  paintScopes();
  paintPicker();

  const coverBody = el("div.iai-pane", {}, [
    el("p.iai-lead", {}, [
      "When you are away, AI can reply on the chats you assign. It follows the instructions you write here. It does not invent prices or availability.",
    ]),
    el("label.iai-switch", {}, [
      enabled,
      el("span", {}, ["Enable AI desk"]),
    ]),
    el("h3.iai-sub", {}, ["Which chats"]),
    scopeHost,
    pickerHost,
    el("h3.iai-sub", {}, ["How AI should talk"]),
    context,
    note,
    el("div.iai-actions", {}, [saveBtn]),
  ]);

  const tabs = el("div.iai-tabs");
  const healthHost = el("div.iai-health.iai-pane");
  healthHost.hidden = true;
  let deskTab = "cover";
  const paintDeskTabs = () => {
    if (!isAdmin()) return;
    clear(tabs);
    [
      ["cover", "AI cover"],
      ["health", "Conversation Health"],
    ].forEach(([id, label]) => {
      tabs.append(
        el(
          "button.iai-tab",
          {
            type: "button",
            class: deskTab === id ? "iai-tab--on" : "",
            onclick: () => {
              deskTab = id;
              coverBody.hidden = id !== "cover";
              healthHost.hidden = id !== "health";
              paintDeskTabs();
            },
          },
          [label]
        )
      );
    });
  };
  if (isAdmin()) paintDeskTabs();

  const dialog = modal(
    "AI desk",
    el("div.modal__body.iai", {}, [isAdmin() ? tabs : null, coverBody, isAdmin() ? healthHost : null]),
    { wide: true }
  );
  glassSheet(dialog);
  if (isAdmin()) {
    dialog.box.classList.add("iai-modal--health");
    paintHealth(healthHost, {
      onOpenChat: (id) => openChatFromHealth(id, dialog.close),
    });
  }

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    try {
      await inboxAi.saveDesk({
        enabled: enabled.checked,
        scope: enabled.checked ? scope : "off",
        context: context.value,
        selected_ids: [...selected.keys()],
      });
      toast("AI desk saved");
      dialog.close();
      paintThreadButton();
    } catch (error) {
      toast(error?.message || "Could not save AI desk", "err");
      saveBtn.disabled = false;
    }
  });
}

async function openCover(conversationId) {
  if (!conversationId) {
    toast("Open a chat first", "err");
    return;
  }
  let data;
  try {
    data = await inboxAi.cover(conversationId);
  } catch (error) {
    toast(error?.message || "Could not load AI cover", "err");
    return;
  }

  const name = data.conversation?.name || data.conversation?.wa_id || "this chat";
  const enabled = el("input", { type: "checkbox", checked: Boolean(data.enabled) });
  const context = contextField(
    data.context,
    `What should AI say to ${name}? Budget, project, tone, what not to promise.`
  );
  const saveBtn = el("button.btn.btn--primary.iai-save", { type: "button" }, ["Save for this chat"]);
  const paused = Boolean(data.enabled && data.paused_at);
  const banner = paused
    ? el("p.iai-banner", {}, [
        "You replied in this chat, so AI paused. Tick cover and save to hand it back.",
      ])
    : null;
  const origin = data.origin === "desk"
    ? el("p.iai-muted", {}, ["Your AI desk would already cover this chat. Saving here gives this client their own instructions."])
    : null;

  const dialog = modal(
    `AI · ${name}`,
    el("div.modal__body.iai", {}, [
      el("p.iai-lead", {}, [
        "Write how AI should talk to this client. These instructions win over your global desk for this chat only.",
      ]),
      banner,
      el("label.iai-switch", {}, [
        enabled,
        el("span", {}, ["Cover this chat with AI"]),
      ]),
      el("h3.iai-sub", {}, ["Instructions for this client"]),
      context,
      origin,
      data.openai_configured
        ? null
        : el("p.iai-note", {}, ["OpenAI is not configured, so AI cannot send yet."]),
      el("div.iai-actions", {}, [saveBtn]),
    ]),
    { wide: true }
  );
  glassSheet(dialog);

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    try {
      await inboxAi.saveCover(conversationId, {
        enabled: enabled.checked,
        context: context.value,
        resume: true,
      });
      toast(enabled.checked ? "AI will cover this chat" : "AI cover off for this chat");
      dialog.close();
      paintThreadButton();
    } catch (error) {
      toast(error?.message || "Could not save", "err");
      saveBtn.disabled = false;
    }
  });
}

async function rememberMe(next) {
  if (next && typeof next === "object") me = next;
  if (!me) {
    try {
      me = await auth.me();
    } catch {
      /* guest / still signing in */
    }
  }
  injectMenu();
}

function mount() {
  if (mounted) return;
  mounted = true;
  watchConversationFetches();
  injectMenu();
  paintThreadButton();
  observeThread();
  rememberMe();
}

window.addEventListener("wa:ready", (event) => {
  rememberMe(event.detail?.me);
  mount();
});
if (document.querySelector(".sidebar__menu") || document.querySelector(".thread__tools")) {
  mount();
}
