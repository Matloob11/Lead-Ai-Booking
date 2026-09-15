/**
 * Who covers which QR-linked phone.
 *
 * The Business Platform numbers have their own screen; this is the same job for
 * the phones linked by scanning a QR code, and it is deliberately a second
 * screen rather than a section bolted onto the first. They are different things:
 * those numbers are rows in our own database, these are sessions that belong to
 * the OpenWA gateway and are named by a UUID it issues. A phone can vanish from
 * this list because somebody unlinked a handset somewhere else entirely.
 *
 * Laid out like Numbers Management, and wearing its `na-` classes rather than a
 * second set of its own: an admin should not have to learn two ways to say the
 * same thing. Pick the phone, pick the agent, save.
 *
 * One agent does not see another's chats because of anything drawn here. Their
 * OpenWA key is scoped to exactly the sessions ticked on this screen and the
 * gateway enforces it; an agent with nothing assigned opens Linked devices to an
 * empty list, which is the intended answer rather than a failure.
 */

import { el, clear, modal, debounce } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { catalog, linkedPhones, asList } from "../api/api.js";

export function openLinkedPhonesAdmin() {
  const list = el("div.na-rows");
  const search = el("input.field.na-search", {
    type: "text",
    placeholder: "Find a phone, number, or assigned agent…",
    autocomplete: "off",
  });
  const summary = el("div.na-summary");

  const body = el("div.na", {}, [
    el("p.na-note", {}, [
      "Assign QR-linked phones to agents. An agent sees the chats on the phones " +
        "listed here for them, and nothing else.",
    ]),
    // Wrapped, not placed bare: `.na-search` carries `flex: 1 1 220px`, which is
    // a width inside `.na-toolbar`'s row and a *height* inside `.na`'s column —
    // dropped straight in, the box grew to fill the dialog.
    el("div.na-toolbar", {}, [search]),
    summary,
    list,
  ]);

  const dialog = modal("Linked phones", body, { wide: true });
  let rows = [];

  search.addEventListener("input", debounce(applyFilter, 120));
  load();

  async function load() {
    clear(list).append(el("div.na-empty", {}, ["Loading linked phones…"]));

    let phones = [];
    let agents = [];
    let reachable = true;
    try {
      const [sessions, roster] = await Promise.all([linkedPhones.list(), catalog.agents()]);
      phones = sessions.sessions || [];
      reachable = sessions.reachable !== false;
      agents = asList(roster, "agents");
    } catch (error) {
      clear(list).append(
        el("div.na-empty", {}, [`Could not read the linked phones. ${error?.message || ""}`])
      );
      return;
    }

    clear(list);
    clear(summary);

    // Said plainly rather than left to be inferred from a short list: when the
    // gateway is unreachable these rows are the last roster we recorded, and
    // saving still works, because the assignment is ours and not OpenWA's.
    if (!reachable) {
      summary.append(
        el("div.na-status.na-status--err", {}, [
          icon("alert", { size: 14 }),
          " The gateway did not answer — showing the roster as last recorded. Changes still save.",
        ])
      );
    }

    if (!phones.length) {
      clear(list).append(
        el("div.na-empty", {}, [
          "No phones are linked yet. Open Linked devices and scan a QR code to add one.",
        ])
      );
      return;
    }

    const assignedCount = phones.filter((p) => (p.agents || []).length).length;
    summary.append(
      el("div.na-note", {}, [
        `${phones.length} linked phone${phones.length === 1 ? "" : "s"} · `,
        `${assignedCount} assigned · `,
        el("strong", {}, [`${phones.length - assignedCount} unassigned`]),
      ])
    );

    rows = phones.map((phone) => phoneCard(phone, agents));
    for (const row of rows) list.append(row.node);
    applyFilter();
  }

  /** Narrowed by phone name, number, or the name of anyone assigned to it. */
  function applyFilter() {
    const term = search.value.trim().toLowerCase();
    let shown = 0;
    for (const row of rows) {
      const hit = !term || row.haystack().includes(term);
      row.node.hidden = !hit;
      if (hit) shown++;
    }
    const none = list.querySelector(".na-empty--filtered");
    if (!shown && !none) {
      list.append(el("div.na-empty.na-empty--filtered", {}, ["Nothing matches that."]));
    } else if (shown && none) {
      none.remove();
    }
  }

  function phoneCard(phone, agents) {
    let assigned = (phone.agents || []).map(Number);
    let saved = [...assigned];

    const chips = el("div.na-chips");
    const pickInput = el("input.na-pick__input", {
      type: "text",
      placeholder: "+ Assign an agent…",
      autocomplete: "off",
      role: "combobox",
      "aria-expanded": "false",
    });
    const pickMenu = el("div.na-pick__menu", { hidden: true, role: "listbox" });
    const status = el("span.na-status");
    const save = el("button.btn.btn--sm.na-save", { type: "button", disabled: true }, ["Save Changes"]);

    const nameOf = (id) => {
      const agent = agents.find((a) => Number(a.id) === Number(id));
      const name = agent?.display_name || agent?.username || `Agent ${id}`;
      const community = String(agent?.community || "").trim();
      return community ? `${name} · ${community}` : name;
    };

    const dirty = () =>
      assigned.length !== saved.length || assigned.some((id) => !saved.includes(id));

    function refresh() {
      clear(chips);
      if (!assigned.length) chips.append(el("span.na-empty", {}, ["Unassigned (No agent)"]));

      for (const id of assigned) {
        const name = nameOf(id);
        chips.append(
          el("div.na-chip", {}, [
            el("span.na-chip__name", {}, [name]),
            el(
              "button.na-chip__remove-btn",
              {
                type: "button",
                title: `Remove ${name} from this phone`,
                onclick: () => {
                  assigned = assigned.filter((x) => x !== id);
                  refresh();
                },
              },
              [icon("close", { size: 12 }), " Remove"]
            ),
          ])
        );
      }

      const free = agents.filter((a) => !assigned.includes(Number(a.id)));
      pickInput.disabled = !free.length;
      pickInput.placeholder = free.length ? "+ Assign an agent…" : "All agents assigned";
      paintMenu();

      const changed = dirty();
      save.disabled = !changed;
      save.classList.toggle("na-save--ready", changed);
      if (changed) status.textContent = "Unsaved changes";
      else if (status.textContent === "Unsaved changes") status.textContent = "";
      applyFilter();
    }

    /** Whoever is not already on this phone, narrowed by what has been typed. */
    function candidates() {
      const term = pickInput.value.trim().toLowerCase();
      const free = agents.filter((a) => !assigned.includes(Number(a.id)));
      if (!term) return free;
        const named = (a) =>
          `${a.display_name || a.username || ""} ${a.community || ""}`.toLowerCase();
      // Name-start before match-anywhere: three letters usually mean the
      // beginning of a name, so put those first rather than alphabetically.
      return [
        ...free.filter((a) => named(a).startsWith(term)),
        ...free.filter((a) => !named(a).startsWith(term) && named(a).includes(term)),
      ];
    }

    function paintMenu() {
      const items = candidates();
      clear(pickMenu);
      pickMenu.hidden = !items.length || document.activeElement !== pickInput;
      pickInput.setAttribute("aria-expanded", String(!pickMenu.hidden));
      for (const agent of items.slice(0, 40)) {
        pickMenu.append(
          el(
            "button.na-pick__item",
            {
              type: "button",
              role: "option",
              // mousedown, not click: the input blurs first on click and the
              // menu is hidden before the handler ever runs.
              onmousedown: (event) => {
                event.preventDefault();
                assigned = [...assigned, Number(agent.id)];
                pickInput.value = "";
                refresh();
              },
            },
            [agent.community ? `${agent.display_name || agent.username} · ${agent.community}` : (agent.display_name || agent.username || `Agent ${agent.id}`)]
          )
        );
      }
    }

    pickInput.addEventListener("input", paintMenu);
    pickInput.addEventListener("focus", paintMenu);
    pickInput.addEventListener("blur", () => setTimeout(() => (pickMenu.hidden = true), 120));

    save.addEventListener("click", async () => {
      save.disabled = true;
      status.textContent = "Saving…";
      try {
        await linkedPhones.setAgents(phone.id, assigned, phone.name || "");
        saved = [...assigned];
        status.textContent = "Saved";
        refresh();
      } catch (error) {
        // Left on screen rather than cleared: an admin who does not notice a
        // failed save believes an agent has access they have not been given.
        status.textContent = error?.message || "Could not save";
        save.disabled = false;
      }
    });

    const node = el("div.na-row", {}, [
      el("div.na-head", {}, [
        el("div.na-title", {}, [phone.name || "(unnamed phone)"]),
        el("div.na-phone", {}, [phone.phone ? `+${phone.phone}` : "no number yet"]),
        el("span.na-badge", { class: `na-badge--${phone.status || "unknown"}` }, [
          phone.status || "unknown",
        ]),
      ]),
      el("div.na-body", {}, [
        el("div.na-field", {}, [
          el("div.na-note", {}, ["ASSIGNED AGENTS"]),
          chips,
          el("div.na-pick", {}, [pickInput, pickMenu]),
        ]),
      ]),
      el("div.na-foot", {}, [status, save]),
    ]);

    refresh();

    return {
      node,
      haystack: () =>
        [phone.name || "", phone.phone || "", ...assigned.map(nameOf)].join(" ").toLowerCase(),
    };
  }

  return dialog;
}
