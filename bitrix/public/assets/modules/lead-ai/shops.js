/**
 * The International City shops playbook in the Lead AI screen.
 *
 * - The AI settings dialog: the facts the assistant may quote in a shops chat
 *   (the three shop types with their sizes and yearly rents, the clusters,
 *   cheques, licences and how a viewing works), the brand it speaks for and
 *   the agent a booked client meets. GET/PUT /api/leadai/settings/ carry them
 *   as shops_facts, brand_name and viewing_agent_name; the server checks every
 *   value and answers errors keyed "shops_facts.types.1.rent_to" and so on.
 * - The thread header's "Follow-up 12 Nov" chip: the customer said yes to
 *   "Should I check back with you in a month?" (lead_ai_ai.followup_due_at);
 *   and "Follow-up waits" while Template B is not approved on the chat's
 *   number (lead_ai_ai.followup_note).
 *
 * Everything is built with el(): no innerHTML, whatever an admin typed.
 */

import { el } from "../../core/dom.js";

const TYPE_NUMBERS = [
  ["size_from", "Size from"],
  ["size_to", "Size to"],
  ["rent_from", "Rent from"],
  ["rent_to", "Rent to"],
  ["cheapest", "From price"],
];
const TEXTS = [
  ["cheques", "Payment", "How customers may pay, e.g. 1 to 4 cheques."],
  ["licences", "Licences", "Which trade licences the shops take."],
  ["viewing", "Viewing", "How a viewing works: the client comes to the office, our agent drives them to the shops."],
];
const NUMBER = new Intl.NumberFormat("en-US");
const DAY_MONTH = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Dubai" });

function factsOf(data) {
  const facts = data && typeof data.shops_facts === "object" && data.shops_facts ? data.shops_facts : {};
  return {
    types: Array.isArray(facts.types) ? facts.types : [],
    clusters: Array.isArray(facts.clusters) ? facts.clusters : [],
    cheques: String(facts.cheques ?? ""),
    licences: String(facts.licences ?? ""),
    viewing: String(facts.viewing ?? ""),
  };
}

function money(value) {
  const n = Number(value);
  return Number.isFinite(n) ? NUMBER.format(n) : String(value ?? "");
}

/** "Follow-up 12 Nov" when the shops assistant plans to check back with this customer; else null. */
export function followUpChip(conversation) {
  const ai = conversation?.lead_ai_ai;
  if (!ai?.followup_due_at) return null;
  let label = String(ai.followup_label || "").trim();
  if (!label) {
    const date = new Date(ai.followup_due_at);
    label = Number.isNaN(date.getTime()) ? "" : DAY_MONTH.format(date);
  }
  if (!label) return null;
  return el(
    "span.lai-chip.lai-chip--followup",
    { title: "The customer asked us to check back with them; the follow-up goes out on this day (Dubai time)." },
    [`Follow-up ${label}`]
  );
}

/**
 * "Follow-up waits" when the chat's automatic follow-up (Template B) cannot go yet because the
 * template is not approved on its number (lead_ai_ai.followup_note, the server's own words); else null.
 */
export function followUpNote(conversation) {
  const note = String(conversation?.lead_ai_ai?.followup_note || "").trim();
  if (!note) return null;
  return el("span.lai-chip.lai-chip--wait", { title: note }, ["Follow-up waits"]);
}

/** The shops facts as read-only rows, for an agent who cannot change the settings. */
export function shopsValues(data) {
  const facts = factsOf(data);
  const rows = facts.types.map((type, index) =>
    el("tr", {}, [
      el("th", { scope: "row" }, [`Type ${index + 1}`]),
      el("td", {}, [String(type?.label ?? "")]),
      el("td", {}, [`${money(type?.size_from)}-${money(type?.size_to)} sq ft`]),
      el("td", {}, [`AED ${money(type?.rent_from)}-${money(type?.rent_to)}`]),
      el("td", {}, [`AED ${money(type?.cheapest)}`]),
    ])
  );
  return el("div.lai-shops", {}, [
    el("dl.lai-set__grid", {}, [
      el("dt", {}, ["Brand"]),
      el("dd", {}, [String(data?.brand_name || "Not set")]),
      el("dt", {}, ["Viewing agent"]),
      el("dd", {}, [String(data?.viewing_agent_name || "our agent")]),
      el("dt", {}, ["Clusters"]),
      el("dd", {}, [facts.clusters.join(", ") || "None"]),
      ...TEXTS.flatMap(([key, label]) => [el("dt", {}, [label]), el("dd", {}, [facts[key] || "Not set"])]),
    ]),
    el("div.lai-shops__scroll", {}, [
      el("table.lai-shops__table", {}, [
        el("thead", {}, [
          el("tr", {}, ["Type", "Name", "Size", "Yearly rent", "From"].map((title) => el("th", { scope: "col" }, [title]))),
        ]),
        el("tbody", {}, rows),
      ]),
    ]),
  ]);
}

/**
 * The editable shops part of the settings form.
 *
 * @returns {{ node: HTMLElement | null, changes: () => object, showError: (key: string, message: string) => HTMLElement | null, clearErrors: () => void }}
 *   changes() gives only the keys that differ from `data`; showError() marks
 *   the input a server error names and returns it (null when it names none here).
 *   A server that sends no shops_facts (older than this screen) gets no fieldset
 *   and nothing is sent for it.
 */
export function shopsForm(data) {
  if (!data || typeof data.shops_facts !== "object" || !data.shops_facts) {
    return { node: null, changes: () => ({}), showError: () => null, clearErrors: () => {} };
  }
  const facts = factsOf(data);
  const inputs = new Map(); // error key -> input
  const errorList = el("ul.lai-shops__errors", { hidden: true, role: "alert" });
  const messages = new Map(); // error key -> message

  function track(key, input) {
    inputs.set(key, input);
    input.addEventListener("input", () => {
      if (!messages.has(key)) return;
      messages.delete(key);
      input.removeAttribute("aria-invalid");
      drawErrors();
    });
    return input;
  }

  function textField(key, label, hint, value, { placeholder = "", max = 300 } = {}) {
    const id = `lai-shops-${key.replace(/\W+/g, "-")}`;
    const input = track(
      key,
      el("input.lai-set__input", { id, type: "text", value, placeholder, maxLength: max, autocomplete: "off", "aria-describedby": `${id}-hint` })
    );
    return el("div.lai-set__field", {}, [
      el("label.lai-set__label", { for: id }, [label]),
      input,
      el("div.lai-set__hint", { id: `${id}-hint` }, [hint]),
    ]);
  }

  const brand = textField("brand_name", "Brand", "The company the assistant speaks for in shops chats.", String(data?.brand_name || ""), {
    max: 80,
  });
  const agent = textField(
    "viewing_agent_name",
    "Viewing agent",
    'The name a booked client is told they will meet. Leave empty for "our agent".',
    String(data?.viewing_agent_name || ""),
    { placeholder: "our agent", max: 60 }
  );

  const body = el("tbody");
  for (let index = 0; index < Math.max(3, facts.types.length); index += 1) {
    const type = facts.types[index] || {};
    const prefix = `shops_facts.types.${index}`;
    const label = track(
      `${prefix}.label`,
      el("input.lai-set__input.lai-shops__text", {
        type: "text",
        value: String(type.label ?? ""),
        maxLength: 40,
        autocomplete: "off",
        "aria-label": `Type ${index + 1} name`,
      })
    );
    const cells = TYPE_NUMBERS.map(([key, title]) =>
      el("td", {}, [
        track(
          `${prefix}.${key}`,
          el("input.lai-set__input.lai-shops__num", {
            type: "number",
            min: 1,
            step: 1,
            inputMode: "numeric",
            value: type[key] === undefined || type[key] === null ? "" : String(type[key]),
            "aria-label": `Type ${index + 1} ${title.toLowerCase()}`,
          })
        ),
      ])
    );
    body.append(el("tr", {}, [el("th", { scope: "row" }, [`Type ${index + 1}`]), el("td", {}, [label]), ...cells]));
  }
  const table = el("table.lai-shops__table", {}, [
    el("thead", {}, [
      el("tr", {}, [
        el("th", { scope: "col" }, ["Type"]),
        el("th", { scope: "col" }, ["Name"]),
        ...TYPE_NUMBERS.map(([, title]) => el("th", { scope: "col" }, [title])),
      ]),
    ]),
    body,
  ]);
  track("shops_facts.types", table);

  const clusters = textField(
    "shops_facts.clusters",
    "Clusters",
    "The International City clusters with shops, separated by commas.",
    facts.clusters.join(", ")
  );
  const texts = TEXTS.map(([key, label, hint]) => textField(`shops_facts.${key}`, label, hint, facts[key]));

  const node = el("fieldset.lai-shops", {}, [
    el("legend.lai-shops__legend", {}, ["International City shops"]),
    el("p.lai-set__hint", {}, [
      "What the assistant may quote in a shops campaign's chats: sizes in sq ft, rents per year in AED. It never quotes any other figure.",
    ]),
    brand,
    agent,
    el("div.lai-shops__scroll", {}, [table]),
    errorList,
    clusters,
    ...texts,
  ]);

  function drawErrors() {
    errorList.replaceChildren(
      ...[...messages.entries()]
        .filter(([key]) => key.startsWith("shops_facts.types"))
        .map(([key, message]) => el("li", {}, [`${errorLabel(key)}: ${message}`]))
    );
    errorList.hidden = !errorList.childNodes.length;
  }

  function errorLabel(key) {
    const match = /^shops_facts\.types\.(\d+)\.(\w+)$/.exec(key);
    if (!match) return "Shop types";
    const field = match[2] === "label" ? "Name" : TYPE_NUMBERS.find(([name]) => name === match[2])?.[1] || match[2];
    return `Type ${Number(match[1]) + 1} · ${field}`;
  }

  function value(key) {
    return String(inputs.get(key)?.value ?? "").trim();
  }

  function number(key) {
    const text = value(key);
    if (!text) return null;
    const n = Number(text);
    return Number.isFinite(n) ? n : text; // the server says what is wrong with it
  }

  function currentFacts() {
    const types = [];
    for (let index = 0; index < Math.max(3, facts.types.length); index += 1) {
      const prefix = `shops_facts.types.${index}`;
      const row = { label: value(`${prefix}.label`) };
      for (const [key] of TYPE_NUMBERS) row[key] = number(`${prefix}.${key}`);
      types.push(row);
    }
    return {
      types,
      clusters: value("shops_facts.clusters")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      cheques: value("shops_facts.cheques"),
      licences: value("shops_facts.licences"),
      viewing: value("shops_facts.viewing"),
    };
  }

  return {
    node,
    changes() {
      const out = {};
      const next = currentFacts();
      if (JSON.stringify(next) !== JSON.stringify(factsOf({ shops_facts: { ...facts, types: facts.types.map(normalType) } }))) {
        out.shops_facts = next;
      }
      if (value("brand_name") !== String(data?.brand_name || "")) out.brand_name = value("brand_name");
      if (value("viewing_agent_name") !== String(data?.viewing_agent_name || "")) out.viewing_agent_name = value("viewing_agent_name");
      return out;
    },
    showError(key, message) {
      const input = inputs.get(key) || (key === "shops_facts" ? table : null);
      if (!input) return null;
      messages.set(key, String(message));
      input.setAttribute("aria-invalid", "true");
      if (!key.startsWith("shops_facts.types")) {
        // A plain field shows its message under itself, like the rest of the form.
        const field = input.closest?.(".lai-set__field");
        let error = field?.querySelector?.(".lai-set__err");
        if (field && !error) {
          error = el("div.lai-set__err");
          field.append(error);
        }
        if (error) {
          error.textContent = String(message);
          error.hidden = false;
        }
      }
      drawErrors();
      return input === table ? table.querySelector("input") || null : input;
    },
    clearErrors() {
      for (const [key, input] of inputs) {
        input.removeAttribute("aria-invalid");
        if (!key.startsWith("shops_facts.types")) {
          const error = input.closest?.(".lai-set__field")?.querySelector?.(".lai-set__err");
          if (error) {
            error.hidden = true;
            error.textContent = "";
          }
        }
      }
      messages.clear();
      drawErrors();
    },
  };
}

/** A stored type, with the keys the form sends, so an untouched form sends nothing. */
function normalType(type) {
  const row = { label: String(type?.label ?? "").trim() };
  for (const [key] of TYPE_NUMBERS) {
    const n = Number(type?.[key]);
    row[key] = type?.[key] === undefined || type?.[key] === null || type?.[key] === "" ? null : Number.isFinite(n) ? n : type[key];
  }
  return row;
}
