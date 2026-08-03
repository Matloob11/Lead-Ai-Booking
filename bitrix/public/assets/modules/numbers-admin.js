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
    const term = search.value.trim().toLowerCase();
    let shown = 0;

    for (const row of rows.values()) {
      const hit = !term || row.haystack().includes(term);
      const free = !onlyFree.checked || row.assignedCount() === 0;
      const isVisible = hit && free;
      row.node.hidden = !isVisible;
      row.node.style.display = isVisible ? "" : "none";
      if (isVisible) shown++;
    }

    const empty = [...rows.values()].filter((r) => r.assignedCount() === 0).length;
    clear(summary).append(
      `${numbers.length} total numbers · ${numbers.length - empty} assigned · `,
      el("strong", {}, [`${empty} unassigned`]),
      term || onlyFree.checked ? ` · showing ${shown}` : ""
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
    const picker = el("select.na-picker");
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
      clear(picker).append(
        el("option", { value: "" }, [free.length ? "+ Assign an agent…" : "All agents assigned"]),
        ...free.map((agent) =>
          el("option", { value: String(agent.id) }, [
            agent.numbers?.length
              ? `${agent.display_name} — holds ${agent.numbers.length} ${agent.numbers.length === 1 ? "number" : "numbers"}`
              : agent.display_name,
          ])
        )
      );
      picker.disabled = !free.length;

      const changed = dirty();
      save.disabled = !changed;
      save.classList.toggle("na-save--ready", changed);
      if (changed && !status.textContent) status.textContent = "Unsaved changes";
      if (!changed && status.textContent === "Unsaved changes") status.textContent = "";
      applyFilter();
    }

    picker.addEventListener("change", () => {
      const id = Number(picker.value);
      picker.value = "";
      if (!id) return;
      assigned.push(id);

      if (!label.value.trim() && assigned.length === 1) {
        label.value = agentById(id)?.display_name || "";
      }
      refresh();
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
      haystack: () =>
        [
          number.phone_number,
          label.value,
          number.display_name || "",
          ...assigned.map((id) => agentById(id)?.display_name || ""),
        ]
          .join(" ")
          .toLowerCase(),
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
    const list = el("div.na-rows", {}, numbers.map(numberRow));

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
