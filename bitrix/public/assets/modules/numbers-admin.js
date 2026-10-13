/**
 * Admin screen: name each WhatsApp number and say who works it.
 *
 * The gateway returns no name for a channel, so without a label the panel can
 * only print digits — and twenty-one identical-looking numbers are impossible
 * to tell apart. Naming and assignment live on one screen because in practice
 * they are the same decision: a number is "Ahmed's", so it gets Ahmed's name.
 *
 * Assignment reads as a roster, not a form control: who holds this number is a
 * list of names you can see at a glance and take one off, rather than a
 * scrolling multi-select where the answer is whichever rows happen to be
 * highlighted.
 */

import { catalog } from "../api/api.js";
import { el, clear, debounce, modal, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { renderAgentLookup } from "./agent-numbers.js";

const badge = (text, tone) => el("span.na-badge", { class: tone ? `na-badge--${tone}` : "" }, [text]);

function agentCaption(agent, fallbackId) {
  const name = String(agent?.display_name || `Agent ${fallbackId ?? ""}`).trim();
  const community = String(agent?.community || "").trim();
  return community ? `${name} · ${community}` : name;
}

function copyText(value) {
  const text = String(value || "");
  if (!text) return;
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(
      () => toast("Copied", "ok"),
      () => toast("Could not copy", "err")
    );
    return;
  }
  toast("Could not copy", "err");
}

/**
 * What is worth flagging about a number.
 */
function flagsFor(number) {
  const templates = number.template_count;
  const chats = number.conversation_count;
  const flags = [];

  if (templates === 0) {
    flags.push(badge("No approved templates", "warn"));
  } else if (templates > 0) {
    flags.push(badge(`${templates} template${templates === 1 ? "" : "s"}`));
  }

  if (chats) flags.push(badge(`${chats} chat${chats === 1 ? "" : "s"}`));
  if (number.template_sync_error) {
    // Quotes the gateway. "Invalid WhatsApp configuration." has so far always
    // meant the Business ID typed here is not one alots knows.
    flags.push(badge(`Templates cannot be listed — ${number.template_sync_error}`, "warn"));
  }
  return flags;
}

/**
 * @param {{onSaved?: (numbers: Array) => void}} options
 */
export function openNumbersAdmin({ onSaved } = {}) {
  const body = el("div.modal__body.na", {}, [el("div.na-note", {}, ["Loading numbers & agents…"])]);
  const dialog = modal("Numbers Management", body, { wide: true });

  let numbers = [];
  let agents = [];
  const rows = new Map();

  /* ------------------------------------------------------------- toolbar */

  const search = el("input.na-search", {
    type: "text",
    placeholder: "Find number, name, community, or assigned agent…",
    autocomplete: "off",
    spellcheck: false,
  });
  const onlyFree = el("input", { type: "checkbox" });
  const summary = el("div.na-summary");
  const viewNumbers = el("button.na-tab.is-on", { type: "button" }, ["By number"]);
  const viewAgents = el("button.na-tab", { type: "button" }, ["By agent"]);
  const agentSearch = el("input.na-search", {
    type: "text",
    placeholder: "Type an agent name…",
    autocomplete: "off",
    spellcheck: false,
  });
  const agentResults = el("div.an-results");
  const agentPane = el("div.na-agent-pane", { hidden: true }, [
    el("p.na-note", {}, [
      "Search an agent to see every Official API number assigned to them. This list updates after you save on By number.",
    ]),
    agentSearch,
    agentResults,
  ]);
  const numbersPane = el("div.na-numbers-pane");
  let currentView = "number";

  const addBtn = el("button.btn.btn--sm.na-add-btn", { type: "button" }, ["Add number"]);
  const syncBtn = el("button.btn.btn--sm", { type: "button" }, ["Sync from gateway"]);
  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    syncBtn.textContent = "Syncing…";
    try {
      await catalog.syncNumbers();
      toast("Numbers synced", "ok");
      load();
    } catch (err) {
      toast(err.message || "Sync failed", "err");
    } finally {
      syncBtn.disabled = false;
      syncBtn.textContent = "Sync from gateway";
    }
  });
  const toolbar = el("div.na-toolbar", {}, [
    search,
    el("label.na-toggle", {}, [onlyFree, el("span", {}, ["Only unassigned numbers"])]),
    syncBtn,
    addBtn,
  ]);

  function typingInsideRow() {
    const active = document.activeElement;
    return Boolean(active && typeof active.closest === "function" && active.closest(".na-row"));
  }

  function applyFilter({ reorder = true } = {}) {
    const raw = search.value.trim().toLowerCase();
    // Digits on their own, so a number can be found by any run of digits inside
    // it. Nobody types a WhatsApp number the way it is stored: "+971 52 407
    // 7268", "0524077268" and "52 407" are all the same number to a person, and
    // matching the typed string literally found none of them.
    const typedDigits = raw.replace(/\D/g, "");
    let shown = 0;

    // Ordered, not just filtered. With twenty-one rows in a scrolling box,
    // "it matched" is only useful if the match is where the eye already is.
    const ranked = [];

    for (const row of rows.values()) {
      const rank = row.rank(raw, typedDigits);
      // "Only unassigned" uses the saved roster. A draft assign stays on screen
      // so Save is still reachable. Dirty rows never hide mid-edit.
      const savedFree = row.savedAssignedCount() === 0;
      const free = !onlyFree.checked || savedFree || row.isDirty();
      const isVisible = rank > 0 && free;
      row.node.hidden = !isVisible;
      row.node.classList.toggle("is-dirty", row.isDirty());
      if (isVisible) {
        shown++;
        ranked.push({ node: row.node, rank });
      }
    }

    // Moving a row that still holds the caret is what stole focus after one
    // character. Rank while idle; leave the DOM alone while somebody is typing.
    if (raw && ranked.length && reorder && !typingInsideRow()) {
      const list = ranked[0].node.parentElement;
      ranked.sort((a, b) => b.rank - a.rank);
      for (const { node } of ranked) list.append(node);
    }

    const empty = [...rows.values()].filter((r) => r.savedAssignedCount() === 0).length;
    clear(summary).append(
      `${numbers.length} total numbers · ${numbers.length - empty} assigned · `,
      el("strong", {}, [`${empty} unassigned`]),
      raw || onlyFree.checked ? ` · showing ${shown}` : ""
    );
  }

  function paintAgentView() {
    renderAgentLookup(agentResults, { agents, numbers, query: agentSearch.value });
  }

  function setView(which) {
    currentView = which === "agent" ? "agent" : "number";
    const byAgent = currentView === "agent";
    viewNumbers.classList.toggle("is-on", !byAgent);
    viewAgents.classList.toggle("is-on", byAgent);
    numbersPane.hidden = byAgent;
    agentPane.hidden = !byAgent;
    if (byAgent) {
      paintAgentView();
      agentSearch.focus();
    }
  }

  viewNumbers.addEventListener("click", () => setView("number"));
  viewAgents.addEventListener("click", () => setView("agent"));
  agentSearch.addEventListener("input", debounce(paintAgentView, 120));
  search.addEventListener("input", debounce(() => applyFilter({ reorder: true }), 150));
  onlyFree.addEventListener("change", () => applyFilter({ reorder: false }));

  /* ----------------------------------------------------------------- row */

  function numberRow(number) {
    let assigned = (number.agents || []).map((a) => a.agent_id);
    let savedAssigned = [...assigned];
    let savedLabel = number.label || "";
    let savedCommunity = number.community || "";
    const communityByAgent = {};
    for (const row of number.agents || []) {
      communityByAgent[row.agent_id] = row.community || "";
    }

    const label = el("input.na-input", {
      type: "text",
      value: savedLabel,
      placeholder: number.display_name || number.phone_number,
      autocomplete: "off",
      spellcheck: false,
    });
    const community = el("input.na-input", {
      type: "text",
      value: savedCommunity,
      placeholder: "e.g. Damac Hills 2",
      maxlength: "120",
      autocomplete: "off",
      spellcheck: false,
    });

    const chips = el("div.na-chips");

    /**
     * The agent picker: a box you type into, not a list you scroll.
     *
     * It was a <select>. With twenty-odd agents that means opening a dropdown
     * and reading down it, and a native select cannot be searched by more than
     * whatever the browser's own first-letter jump does — which lands on the
     * first name beginning with that letter and goes no further. Typing three
     * letters of a surname now narrows it as you type.
     */
    const pickInput = el("input.na-pick__input", {
      type: "text",
      placeholder: "+ Assign an agent…",
      autocomplete: "off",
      role: "combobox",
      "aria-expanded": "false",
    });
    const pickMenu = el("div.na-pick__menu", { hidden: true, role: "listbox" });
    const picker = el("div.na-pick", {}, [pickInput, pickMenu]);
    const status = el("span.na-status");
    const save = el("button.btn.btn--sm.na-save", { type: "button", disabled: true }, ["Save Changes"]);
    const title = el("div.na-title", {}, [number.title || number.phone_number]);
    const areaBadge = el("span.na-community", { hidden: !savedCommunity }, [savedCommunity]);

    const agentById = (id) => agents.find((a) => a.id === id);

    const dirty = () =>
      label.value.trim() !== savedLabel ||
      community.value.trim() !== savedCommunity ||
      assigned.length !== savedAssigned.length ||
      assigned.some((id) => !savedAssigned.includes(id)) ||
      assigned.some((id) => (communityByAgent[id] || "") !== (agentById(id)?.community || ""));

    function markDirty() {
      const changed = dirty();
      save.disabled = !changed;
      save.classList.toggle("na-save--ready", changed);
      node?.classList.toggle("is-dirty", changed);
      if (changed && !status.textContent) status.textContent = "Unsaved changes";
      if (!changed && status.textContent === "Unsaved changes") status.textContent = "";
      const area = community.value.trim();
      areaBadge.hidden = !area;
      areaBadge.textContent = area;
    }

    function refresh() {
      clear(chips);
      if (!assigned.length) {
        chips.append(el("span.na-empty", {}, ["Unassigned (No agent)"]));
      }

      for (const id of assigned) {
        const agent = agentById(id);
        const name = agent?.display_name || `Agent ${id}`;
        if (communityByAgent[id] === undefined) {
          communityByAgent[id] = agent?.community || "";
        }
        const communityField = el("input.na-chip__community", {
          type: "text",
          value: communityByAgent[id] || "",
          placeholder: "Community",
          maxlength: "120",
          title: "Community shown next to this agent's name",
          oninput: () => {
            communityByAgent[id] = communityField.value;
            markDirty();
          },
          onclick: (event) => event.stopPropagation(),
        });
        chips.append(
          el("div.na-chip", {}, [
            el("span.na-chip__name", {}, [name]),
            communityField,
            el(
              "button.na-chip__remove-btn",
              {
                type: "button",
                title: `Remove ${name} from this number`,
                onclick: () => {
                  assigned = assigned.filter((x) => x !== id);
                  refresh();
                  applyFilter({ reorder: false });
                },
              },
              [icon("close", { size: 12 }), " Remove"]
            ),
          ])
        );
      }

      const free = agents.filter((a) => !assigned.includes(a.id));
      pickInput.disabled = !free.length;
      pickInput.placeholder = free.length ? "+ Assign an agent…" : "All agents assigned";
      paintMenu();
      markDirty();
    }

    /** Whoever is not already on this number, narrowed by what has been typed. */
    function candidates() {
      const term = pickInput.value.trim().toLowerCase();
      const free = agents.filter((a) => !assigned.includes(a.id));
      if (!term) return free;

      // Name first, then a match anywhere in it — "sha" finds "Shahid" before
      // "Asma Shahid", which is the order somebody typing three letters means.
      const scored = free
        .map((agent) => {
          const name = String(agent.display_name || "").toLowerCase();
          const area = String(agent.community || "").toLowerCase();
          const atName = name.indexOf(term);
          const atArea = area.indexOf(term);
          if (atName < 0 && atArea < 0) return null;
          const at = atName < 0 ? atArea + 10 : atName;
          return { agent, score: atName === 0 || atArea === 0 ? 2 : 1, at };
        })
        .filter(Boolean);

      scored.sort((a, b) => b.score - a.score || a.at - b.at);
      return scored.map((s) => s.agent);
    }

    let marked = 0;

    function placeMenu() {
      const box = pickInput.getBoundingClientRect();
      const spaceBelow = window.innerHeight - box.bottom;
      pickMenu.style.position = "fixed";
      pickMenu.style.left = `${Math.max(8, box.left)}px`;
      pickMenu.style.width = `${Math.max(box.width, 220)}px`;
      pickMenu.style.right = "auto";
      pickMenu.style.zIndex = "80";
      if (spaceBelow < 200 && box.top > spaceBelow) {
        pickMenu.style.top = "auto";
        pickMenu.style.bottom = `${Math.max(8, window.innerHeight - box.top + 4)}px`;
      } else {
        pickMenu.style.bottom = "auto";
        pickMenu.style.top = `${box.bottom + 4}px`;
      }
    }

    function paintMenu() {
      const list = candidates();
      marked = Math.min(marked, Math.max(0, list.length - 1));
      clear(pickMenu);
      if (!pickMenu.hidden) placeMenu();

      if (!list.length) {
        pickMenu.append(
          el("div.na-pick__none", {}, [
            pickInput.value.trim() ? "No agent matches that." : "All agents are already on this number.",
          ])
        );
        return;
      }

      list.forEach((agent, index) => {
        const holds = agent.numbers?.length || 0;
        pickMenu.append(
          el(
            "button.na-pick__item",
            {
              type: "button",
              role: "option",
              class: index === marked ? "is-marked" : "",
              // mousedown, not click: the input's blur would close the menu
              // first and the click would land on nothing.
              onmousedown: (event) => {
                event.preventDefault();
                choose(agent.id);
              },
              onmouseenter: () => {
                marked = index;
                for (const [i, node] of [...pickMenu.children].entries()) {
                  node.classList?.toggle("is-marked", i === marked);
                }
              },
            },
            [
              el("span.na-pick__name", {}, [agentCaption(agent, agent.id)]),
              holds
                ? el("span.na-pick__holds", {}, [`${holds} number${holds === 1 ? "" : "s"}`])
                : null,
            ]
          )
        );
      });
    }

    const openMenu = () => {
      if (pickInput.disabled) return;
      marked = 0;
      pickMenu.hidden = false;
      pickInput.setAttribute("aria-expanded", "true");
      paintMenu();
      placeMenu();
    };

    const closeMenu = () => {
      pickMenu.hidden = true;
      pickInput.setAttribute("aria-expanded", "false");
    };

    function choose(id) {
      if (!id) return;
      assigned.push(id);
      pickInput.value = "";
      closeMenu();

      const agent = agentById(id);
      if (!communityByAgent[id]) {
        communityByAgent[id] = agent?.community || community.value.trim() || "";
      }

      if (!label.value.trim() && assigned.length === 1) {
        label.value = agent?.display_name || "";
      }
      refresh();
      applyFilter({ reorder: false });
    }

    pickInput.addEventListener("focus", openMenu);
    pickInput.addEventListener("blur", () => setTimeout(closeMenu, 0));
    pickInput.addEventListener("input", () => {
      marked = 0;
      paintMenu();
      pickMenu.hidden = false;
    });

    pickInput.addEventListener("keydown", (event) => {
      const list = candidates();

      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (pickMenu.hidden) return openMenu();
        marked = Math.max(0, Math.min(list.length - 1, marked + (event.key === "ArrowDown" ? 1 : -1)));
        paintMenu();
        pickMenu.children[marked]?.scrollIntoView({ block: "nearest" });
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        // Only ever the row that is actually highlighted. Guessing at the first
        // match on a bare Enter is how somebody assigns the wrong agent.
        if (!pickMenu.hidden && list[marked]) choose(list[marked].id);
        return;
      }

      if (event.key === "Escape") {
        pickInput.value = "";
        closeMenu();
      }
    });

    label.addEventListener("input", markDirty);
    community.addEventListener("input", markDirty);

    save.addEventListener("click", async () => {
      save.disabled = true;
      status.className = "na-status";
      status.textContent = "Saving…";
      try {
        await catalog.renameNumber(number.id, {
          label: label.value.trim(),
          community: community.value.trim(),
        });
        const updated = await catalog.setNumberAgents(
          number.id,
          assigned.map((id) => ({
            agent_id: id,
            role: "primary",
            community: (communityByAgent[id] || "").trim(),
          }))
        );

        title.textContent = updated.title || updated.phone_number;
        savedLabel = label.value.trim();
        savedCommunity = community.value.trim();
        savedAssigned = [...assigned];

        for (const agent of agents) {
          const holds = (agent.numbers || []).some((n) => n.id === number.id);
          const shouldHold = assigned.includes(agent.id);
          if (shouldHold && !holds) {
            (agent.numbers ||= []).push({ id: number.id, phone_number: number.phone_number });
          } else if (!shouldHold && holds) {
            agent.numbers = agent.numbers.filter((n) => n.id !== number.id);
          }
          if (shouldHold && communityByAgent[agent.id] !== undefined) {
            agent.community = (communityByAgent[agent.id] || "").trim();
          }
        }
        for (const row of rows.values()) row.resync?.();

        status.textContent = "Saved successfully";
        status.className = "na-status na-status--ok";
        [numbers, agents] = await Promise.all([catalog.numbers(), catalog.agents()]);
        refresh();
        applyFilter({ reorder: false });
        if (currentView === "agent") paintAgentView();
        onSaved?.(numbers);
      } catch (error) {
        status.textContent = error.message;
        status.className = "na-status na-status--err";
        save.disabled = false;
      }
    });

    const idsMeta = el("div.na-ids", {}, [
      el("div.na-id", {}, [
        el("span.na-id__k", {}, ["Business ID"]),
        el("span.na-id__v", {}, [number.waba_business_id || "—"]),
      ]),
      el("div.na-id", {}, [
        el("span.na-id__k", {}, ["Phone Number ID"]),
        el("span.na-id__v", {}, [number.phone_number_id || "—"]),
      ]),
      number.source === "manual" ? badge("Manual", "ok") : null,
    ]);

    const webhookRow = number.webhook_url
      ? el("div.na-webhook", {}, [
          el("span.na-id__k", {}, ["Webhook"]),
          el(
            "button.na-webhook__link",
            {
              type: "button",
              title: "Copy webhook URL",
              onclick: () => copyText(number.webhook_url),
            },
            [number.webhook_url]
          ),
        ])
      : null;

    const extras = el("details.na-details", {}, [
      el("summary", {}, ["IDs and webhook"]),
      idsMeta,
      webhookRow,
    ].filter(Boolean));

    const node = el("div.na-row", {}, [
      el("div.na-head", {}, [
        el("div.na-who", {}, [
          el("div.na-title-row", {}, [title, areaBadge]),
          el("div.na-phone", {}, [number.phone_number]),
        ]),
        el("div.na-flags", {}, flagsFor(number)),
      ]),
      el("div.na-body", {}, [
        el("label.na-field", {}, [el("span", {}, ["Name / Label"]), label]),
        el("label.na-field", {}, [el("span", {}, ["Community"]), community]),
        el("div.na-field.na-field--agents", {}, [
          el("span", {}, ["Assigned Agents"]),
          chips,
          el("div.na-picker-wrap", {}, [picker]),
        ]),
        extras,
      ]),
      el("div.na-foot", {}, [status, save]),
    ]);

    rows.set(number.id, {
      node,
      assignedCount: () => assigned.length,
      savedAssignedCount: () => savedAssigned.length,
      isDirty: dirty,
      resync: () => {
        if (!dirty()) refresh();
      },
      /**
       * How well this row answers what was typed. 0 means it does not.
       *
       * Digits are compared against digits, so the punctuation a person puts in
       * a phone number is ignored on both sides. Higher is a better match, and
       * the caller uses that to put the closest ones at the top.
       */
      rank: (raw, typedDigits) => {
        if (!raw) return 1;

        const phoneDigits = String(number.phone_number || "").replace(/\D/g, "");
        if (typedDigits) {
          // The tail matters most: people read a number back from its end, and
          // "7268" should find +971524077268 ahead of anything it merely
          // appears in the middle of.
          if (phoneDigits.endsWith(typedDigits)) return 5;
          if (phoneDigits.startsWith(typedDigits)) return 4;
          if (phoneDigits.includes(typedDigits)) return 3;
        }

        const words = [
          label.value,
          community.value,
          number.display_name || "",
          number.community || "",
          ...assigned.map((id) => agentCaption(agentById(id), id)),
        ]
          .join(" ")
          .toLowerCase();

        if (words.startsWith(raw)) return 2;
        if (words.includes(raw)) return 1;

        // A term with no digits in it was a name search and has already failed;
        // one with digits has been answered above. Anything left is a miss.
        return 0;
      },
    });

    refresh();
    return node;
  }

  /* ---------------------------------------------------------- add number */

  function openAddNumberForm() {
    let canSave = false;
    let saveForce = false;
    const phone = el("input.na-input", {
      type: "text",
      inputmode: "numeric",
      autocomplete: "off",
      placeholder: "971552832895",
    });
    const businessId = el("input.na-input", {
      type: "text",
      inputmode: "numeric",
      autocomplete: "off",
      placeholder: "Business / WABA ID",
    });
    const phoneNumberId = el("input.na-input", {
      type: "text",
      inputmode: "numeric",
      autocomplete: "off",
      placeholder: "Phone Number ID",
    });
    const labelInput = el("input.na-input", {
      type: "text",
      autocomplete: "off",
      placeholder: "e.g. BSP-1",
    });
    const communityInput = el("input.na-input", {
      type: "text",
      autocomplete: "off",
      placeholder: "e.g. Damac Hills 2",
      maxlength: "120",
    });
    const testStatus = el("div.na-add-status");
    const testBtn = el("button.btn.btn--sm", { type: "button" }, ["Test"]);
    const saveBtn = el("button.btn.btn--sm.btn--primary", { type: "button", disabled: true }, [
      "Save",
    ]);

    function setSaveReady({ ok, force }) {
      canSave = !!ok || !!force;
      saveForce = !!force && !ok;
      saveBtn.disabled = !canSave;
      saveBtn.textContent = saveForce ? "Save anyway" : "Save";
    }

    function invalidateTest() {
      canSave = false;
      saveForce = false;
      saveBtn.disabled = true;
      saveBtn.textContent = "Save";
      if (testStatus.classList.contains("na-add-status--ok") || testStatus.classList.contains("na-add-status--warn")) {
        testStatus.className = "na-add-status";
        testStatus.textContent = "Details changed — Test again before saving.";
      }
    }

    for (const field of [phone, businessId, phoneNumberId]) {
      field.addEventListener("input", invalidateTest);
    }

    function payload() {
      return {
        phone_number: phone.value.trim(),
        waba_business_id: businessId.value.trim(),
        phone_number_id: phoneNumberId.value.trim(),
        label: labelInput.value.trim(),
        community: communityInput.value.trim(),
        force: saveForce,
      };
    }

    testBtn.addEventListener("click", async () => {
      const data = payload();
      if (!data.phone_number || !data.waba_business_id || !data.phone_number_id) {
        testStatus.className = "na-add-status na-add-status--err";
        testStatus.textContent = "Fill phone, Business ID, and Phone Number ID first.";
        setSaveReady({ ok: false, force: false });
        return;
      }
      testBtn.disabled = true;
      setSaveReady({ ok: false, force: false });
      testStatus.className = "na-add-status na-add-status--busy";
      testStatus.textContent = "Checking…";
      try {
        const result = await catalog.testNumber({
          phone_number: data.phone_number,
          waba_business_id: data.waba_business_id,
          phone_number_id: data.phone_number_id,
        });
        const ok = !!result?.ok;
        const force = !!result?.allow_force && !ok && !result?.already_exists;
        const name = result?.verified_name ? ` · ${result.verified_name}` : "";
        if (ok) {
          testStatus.className = "na-add-status na-add-status--ok";
          testStatus.textContent = `${result.detail || "Connected"}${name}`;
        } else if (force) {
          testStatus.className = "na-add-status na-add-status--warn";
          testStatus.textContent = result?.detail || "Not on this gateway — you can Save anyway.";
        } else {
          testStatus.className = "na-add-status na-add-status--err";
          testStatus.textContent = result?.detail || "Connection failed";
        }
        if (result?.phone_number_id && result.phone_number_id !== phoneNumberId.value.trim()) {
          phoneNumberId.value = result.phone_number_id;
        }
        if (result?.waba_business_id && result.waba_business_id !== businessId.value.trim()) {
          businessId.value = result.waba_business_id;
        }
        if (result?.phone_number && result.phone_number !== phone.value.trim() && (ok || result.already_exists)) {
          phone.value = result.phone_number;
        }
        setSaveReady({ ok, force });
      } catch (error) {
        testStatus.className = "na-add-status na-add-status--err";
        testStatus.textContent = error.message || "Connection failed";
        setSaveReady({ ok: false, force: false });
      } finally {
        testBtn.disabled = false;
      }
    });

    saveBtn.addEventListener("click", async () => {
      if (!canSave) return;
      saveBtn.disabled = true;
      testBtn.disabled = true;
      testStatus.className = "na-add-status na-add-status--busy";
      testStatus.textContent = "Saving…";
      try {
        await catalog.createNumber(payload());
        toast("Number saved", "ok");
        addDialog.close();
        load();
        onSaved?.(await catalog.numbers());
      } catch (error) {
        testStatus.className = "na-add-status na-add-status--err";
        testStatus.textContent = error.message || "Save failed";
        setSaveReady({ ok: !saveForce, force: saveForce });
        testBtn.disabled = false;
      }
    });

    const form = el("div.modal__body.na-add", {}, [
      el("p.na-note", {}, [
        "Paste credentials from your webbox (OTP or QR). Test against the gateway, then Save. If the number is on another BSP and Test cannot find it here, use Save anyway. Manual numbers stay active even if a sync does not list them yet.",
      ]),
      el("label.na-field", {}, [el("span", {}, ["Phone number"]), phone]),
      el("label.na-field", {}, [el("span", {}, ["Business ID"]), businessId]),
      el("label.na-field", {}, [el("span", {}, ["Phone Number ID"]), phoneNumberId]),
      el("label.na-field", {}, [el("span", {}, ["Label (optional)"]), labelInput]),
      el("label.na-field", {}, [el("span", {}, ["Community (optional)"]), communityInput]),
      testStatus,
      el("div.na-add-actions", {}, [testBtn, saveBtn]),
    ]);

    const addDialog = modal("Add Official API number", form, { wide: false });
  }

  addBtn.addEventListener("click", openAddNumberForm);

  /* -------------------------------------------------------------- render */

  async function load() {
    try {
      [numbers, agents] = await Promise.all([catalog.numbers(), catalog.agents()]);
    } catch (error) {
      clear(body).append(el("div.alert", {}, [`Could not load: ${error.message}`]));
      return;
    }

    rows.clear();

    // Building the rows is guarded too, not only fetching them.
    //
    // A throw in here used to escape `load()` entirely and leave the dialog on
    // "Loading numbers & agents…" for ever, with the reason only in a console
    // nobody had open. One did: `applyFilter` read a variable named `term` that
    // does not exist, so every row threw on construction and this screen was
    // dead for as long as that typo lived.
    let list;
    try {
      list = el(
        "div.na-rows",
        {},
        numbers.length
          ? numbers.map(numberRow)
          : [el("div.na-empty", {}, ["No WhatsApp numbers yet. Use Add number to paste credentials."])]
      );
    } catch (error) {
      console.error("[a7-wa] numbers admin failed to draw:", error);
      clear(body).append(
        el("div.alert", {}, [`This screen could not be drawn: ${error.message}`])
      );
      return;
    }

    clear(numbersPane).append(toolbar, summary, list);
    const children = [
      el("p.na-note", {}, [
        "Name a number, assign agents, then Save. Unsaved cards stay visible even with Only unassigned ticked. Use By agent to look up every number one person holds.",
      ]),
      agents.length
        ? null
        : el("div.alert", {}, [
            "No agents yet. An agent appears here the first time they open the panel from Bitrix.",
          ]),
      el("div.na-tabs", {}, [viewNumbers, viewAgents]),
      numbersPane,
      agentPane,
    ].filter(Boolean);

    clear(body).append(...children);
    applyFilter({ reorder: false });
    if (currentView === "agent") setView("agent");
  }

  load();
  return dialog;
}
