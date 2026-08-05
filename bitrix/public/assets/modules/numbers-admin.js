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
import { el, clear, debounce, modal } from "../core/dom.js";

const badge = (text, tone) => el("span.na-badge", { class: tone ? `na-badge--${tone}` : "" }, [text]);

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
    type: "search",
    placeholder: "Find number, name, or assigned agent…",
  });
  const onlyFree = el("input", { type: "checkbox" });
  const summary = el("div.na-summary");

  const toolbar = el("div.na-toolbar", {}, [
    search,
    el("label.na-toggle", {}, [onlyFree, el("span", {}, ["Only unassigned numbers"])]),
  ]);

  function applyFilter() {
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
      const free = !onlyFree.checked || row.assignedCount() === 0;
      const isVisible = rank > 0 && free;
      row.node.hidden = !isVisible;
      row.node.style.display = isVisible ? "" : "none";
      if (isVisible) {
        shown++;
        ranked.push({ node: row.node, rank });
      }
    }

    // Best first: a number that starts with what was typed before one that
    // merely contains it, and either before a match on somebody's name.
    if (raw && ranked.length) {
      const list = ranked[0].node.parentElement;
      ranked.sort((a, b) => b.rank - a.rank);
      for (const { node } of ranked) list.append(node);
    }

    const empty = [...rows.values()].filter((r) => r.assignedCount() === 0).length;
    clear(summary).append(
      `${numbers.length} total numbers · ${numbers.length - empty} assigned · `,
      el("strong", {}, [`${empty} unassigned`]),
      raw || onlyFree.checked ? ` · showing ${shown}` : ""
    );
  }

  search.addEventListener("input", applyFilter);
  onlyFree.addEventListener("change", applyFilter);

  /* ----------------------------------------------------------------- row */

  function numberRow(number) {
    let assigned = (number.agents || []).map((a) => a.agent_id);
    let savedAssigned = [...assigned];
    let savedLabel = number.label || "";

    const label = el("input.na-input", {
      type: "text",
      value: savedLabel,
      placeholder: number.display_name || number.phone_number,
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

    const agentById = (id) => agents.find((a) => a.id === id);

    const dirty = () =>
      label.value.trim() !== savedLabel ||
      assigned.length !== savedAssigned.length ||
      assigned.some((id) => !savedAssigned.includes(id));

    function refresh() {
      clear(chips);
      if (!assigned.length) {
        chips.append(el("span.na-empty", {}, ["Unassigned (No agent)"]));
      }

      for (const id of assigned) {
        const agent = agentById(id);
        const name = agent?.display_name || `Agent ${id}`;
        chips.append(
          el("div.na-chip", {}, [
            el("span.na-chip__name", {}, [name]),
            el(
              "button.na-chip__remove-btn",
              {
                type: "button",
                title: `Remove ${name} from this number`,
                onclick: () => {
                  assigned = assigned.filter((x) => x !== id);
                  refresh();
                },
              },
              ["Remove ×"]
            ),
          ])
        );
      }

      const free = agents.filter((a) => !assigned.includes(a.id));
      pickInput.disabled = !free.length;
      pickInput.placeholder = free.length ? "+ Assign an agent…" : "All agents assigned";
      paintMenu();

      const changed = dirty();
      save.disabled = !changed;
      save.classList.toggle("na-save--ready", changed);
      if (changed && !status.textContent) status.textContent = "Unsaved changes";
      if (!changed && status.textContent === "Unsaved changes") status.textContent = "";
      applyFilter();
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
          const at = name.indexOf(term);
          if (at < 0) return null;
          return { agent, score: at === 0 ? 2 : 1, at };
        })
        .filter(Boolean);

      scored.sort((a, b) => b.score - a.score || a.at - b.at);
      return scored.map((s) => s.agent);
    }

    let marked = 0;

    function paintMenu() {
      const list = candidates();
      marked = Math.min(marked, Math.max(0, list.length - 1));
      clear(pickMenu);

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
              el("span.na-pick__name", {}, [agent.display_name || `Agent ${agent.id}`]),
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
      paintMenu();
      pickMenu.hidden = false;
      pickInput.setAttribute("aria-expanded", "true");
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

      if (!label.value.trim() && assigned.length === 1) {
        label.value = agentById(id)?.display_name || "";
      }
      refresh();
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

    label.addEventListener("input", refresh);

    save.addEventListener("click", async () => {
      save.disabled = true;
      status.className = "na-status";
      status.textContent = "Saving…";
      try {
        await catalog.renameNumber(number.id, label.value.trim());
        const updated = await catalog.setNumberAgents(
          number.id,
          assigned.map((id) => ({ agent_id: id, role: "primary" }))
        );

        title.textContent = updated.title || updated.phone_number;
        savedLabel = label.value.trim();
        savedAssigned = [...assigned];

        for (const agent of agents) {
          const holds = (agent.numbers || []).some((n) => n.id === number.id);
          const shouldHold = assigned.includes(agent.id);
          if (shouldHold && !holds) {
            (agent.numbers ||= []).push({ id: number.id, phone_number: number.phone_number });
          } else if (!shouldHold && holds) {
            agent.numbers = agent.numbers.filter((n) => n.id !== number.id);
          }
        }
        for (const row of rows.values()) row.resync?.();

        status.textContent = "Saved successfully";
        status.className = "na-status na-status--ok";
        refresh();
        onSaved?.(await catalog.numbers());
      } catch (error) {
        status.textContent = error.message;
        status.className = "na-status na-status--err";
        save.disabled = false;
      }
    });

    const node = el("div.na-row", {}, [
      el("div.na-head", {}, [
        el("div.na-who", {}, [title, el("div.na-phone", {}, [number.phone_number])]),
        el("div.na-flags", {}, flagsFor(number)),
      ]),
      el("div.na-body", {}, [
        el("label.na-field", {}, [el("span", {}, ["Name / Label"]), label]),
        el("div.na-field", {}, [
          el("span", {}, ["Assigned Agents"]),
          chips,
          el("div.na-picker-wrap", {}, [picker]),
        ]),
      ]),
      el("div.na-foot", {}, [status, save]),
    ]);

    rows.set(number.id, {
      node,
      assignedCount: () => assigned.length,
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
          number.display_name || "",
          ...assigned.map((id) => agentById(id)?.display_name || ""),
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

  /* -------------------------------------------------------------- render */

  async function load() {
    try {
      [numbers, agents] = await Promise.all([catalog.numbers(), catalog.agents()]);
    } catch (error) {
      clear(body).append(el("div.alert", {}, [`Could not load: ${error.message}`]));
      return;
    }

    if (!numbers.length) {
      clear(body).append(el("div.na-note", {}, ["No WhatsApp numbers found."]));
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
      list = el("div.na-rows", {}, numbers.map(numberRow));
    } catch (error) {
      console.error("[a7-wa] numbers admin failed to draw:", error);
      clear(body).append(
        el("div.alert", {}, [`This screen could not be drawn: ${error.message}`])
      );
      return;
    }

    const children = [
      el("p.na-note", {}, [
        "Assign numbers to agents and set display names. Changes take effect across the inbox immediately after saving.",
      ]),
      agents.length
        ? null
        : el("div.alert", {}, [
            "No agents yet. An agent appears here the first time they open the panel from Bitrix.",
          ]),
      toolbar,
      summary,
      list,
    ].filter(Boolean);

    clear(body).append(...children);
    applyFilter();
  }

  load();
  return dialog;
}
