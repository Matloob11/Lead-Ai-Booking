/**
 * Admin screen: name each WhatsApp number and say who works it.
 *
 * The gateway returns no name for a channel, so without a label the panel can
 * only print digits — and twenty-one identical-looking numbers are impossible
 * to tell apart. Naming and assignment live on one screen because in practice
 * they are the same decision: a number is "Ahmed's", so it gets Ahmed's name.
 */

import { catalog } from "./api.js";
import { el, clear, modal } from "./dom.js";

/**
 * @param {{onSaved?: (numbers: Array) => void}} options
 *        onSaved fires after every successful row save, with the fresh list, so
 *        the inbox behind can pick up a rename without a reload.
 */
export function openNumbersAdmin({ onSaved } = {}) {
  const body = el("div.modal__body", {}, [el("div.thread__hint", {}, ["Load ho raha hai…"])]);
  const dialog = modal("Numbers", body, { wide: true });

  load();

  async function load() {
    let numbers;
    let agents;
    try {
      [numbers, agents] = await Promise.all([catalog.numbers(), catalog.agents()]);
    } catch (error) {
      clear(body).append(el("div.alert", {}, [`Load nahi hua: ${error.message}`]));
      return;
    }

    if (!numbers.length) {
      clear(body).append(el("div.thread__hint", {}, ["Koi number nahi mila."]));
      return;
    }

    // Node.append() renders a null argument as the text "null", so the
    // conditional notice is filtered out rather than passed through.
    const parts = [
      el("p.modal__note", {}, [
        "Naam sirf yahan rakha jata hai — panel har jagah yehi dikhata hai. " +
          "Naam khali chhorne par number khud dikhne lagega.",
      ]),
      agents.length
        ? null
        : el("div.alert", {}, [
            "Abhi koi agent list mein nahi hai. Agent tab hi banta hai jab wo pehli baar Bitrix se panel kholta hai.",
          ]),
      el("div.numrows", {}, numbers.map((number) => numberRow(number, agents))),
    ].filter(Boolean);

    clear(body).append(...parts);
  }

  function numberRow(number, agents) {
    const assigned = new Set((number.agents || []).map((a) => a.agent_id));

    const label = el("input.field", {
      type: "text",
      value: number.label || "",
      placeholder: number.display_name || number.phone_number,
    });

    const picker = el(
      "select.field.numrow__agents",
      { multiple: true, size: Math.min(4, Math.max(2, agents.length)) },
      agents.map((agent) =>
        el("option", { value: String(agent.id), selected: assigned.has(agent.id) }, [agent.display_name])
      )
    );

    // Naming twenty-one numbers is the tedious part, so assigning someone
    // offers their name as the label. Only when it is still empty — an admin's
    // own wording is never overwritten.
    picker.addEventListener("change", () => {
      if (label.value.trim()) return;
      const [first] = selectedAgents();
      if (first) label.value = agents.find((a) => String(a.id) === String(first.agent_id))?.display_name || "";
    });

    const selectedAgents = () =>
      [...picker.selectedOptions].map((option) => ({ agent_id: Number(option.value), role: "primary" }));

    const status = el("span.numrow__status");
    const save = el("button.btn.btn--primary", { type: "button" }, ["Save"]);

    save.addEventListener("click", async () => {
      save.disabled = true;
      status.className = "numrow__status";
      status.textContent = "Saving…";
      try {
        // Rename first: the roster response is the one we keep, and it carries
        // the new title.
        await catalog.renameNumber(number.id, label.value.trim());
        const updated = await catalog.setNumberAgents(number.id, selectedAgents());

        title.textContent = updated.title || updated.phone_number;
        status.textContent = "Saved";
        status.className = "numrow__status numrow__status--ok";
        onSaved?.(await catalog.numbers());
      } catch (error) {
        status.textContent = error.message;
        status.className = "numrow__status numrow__status--err";
      } finally {
        save.disabled = false;
      }
    });

    const title = el("div.numrow__title", {}, [number.title || number.phone_number]);

    return el("div.numrow", {}, [
      el("div.numrow__who", {}, [title, el("div.numrow__phone", {}, [number.phone_number])]),
      el("label.numrow__field", {}, [el("span", {}, ["Naam"]), label]),
      el("label.numrow__field", {}, [el("span", {}, ["Agents"]), picker]),
      el("div.numrow__actions", {}, [save, status]),
    ]);
  }

  return dialog;
}
