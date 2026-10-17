/**
 * The International City studios and one-bedrooms facts in the Lead AI settings (spec §2.2).
 *
 * What the assistant may quote in a rent or sale chat about a studio or a one-bedroom: the yearly
 * rent bands, the sale price bands, the security deposit, the commission before VAT, the VAT on it,
 * Ejari, the DEWA deposit, and how cheques, chiller and documents work. GET/PUT
 * /api/leadai/settings/ carry them as residential_facts; the server checks every value and answers
 * errors keyed "residential_facts.rent.studio.to" and so on. There are no agent fields: nobody is
 * named to a customer (Q30).
 *
 * Everything is built with el(): no innerHTML, whatever an admin typed.
 */

import { el } from "../../core/dom.js";

const PREFIX = "residential_facts";
// Each row of the bands table: its path in the facts, its label and the numbers it holds.
const BAND_ROWS = [
  ["rent.studio", "Rent · studio, a year", ["from", "to", "average"]],
  ["rent.one_br", "Rent · one-bedroom, a year", ["from", "to"]],
  ["rent.one_br_european", "Rent · one-bedroom in a European cluster, a year", ["from", "to"]],
  ["sale.studio", "Sale · studio", ["from", "to"]],
  ["sale.studio_morocco", "Sale · studio in Morocco", ["from", "to"]],
  ["sale.one_br", "Sale · one-bedroom", ["from", "to"]],
  ["charges.deposit", "Security deposit", ["from", "to"]],
  ["charges.commission.studio", "Commission · studio, before VAT", ["from", "to"]],
  ["charges.commission.one_br", "Commission · one-bedroom, before VAT", ["from", "to"]],
];
const COLUMNS = [
  ["from", "From"],
  ["to", "To"],
  ["average", "Average"],
];
const NUMBERS = [
  ["vat_percent", "VAT on the commission (%)", "Charged on the commission only, never on the rent."],
  ["ejari", "Ejari (AED)", "The tenancy registration fee."],
  ["dewa_deposit", "DEWA deposit (AED)", "Refundable, paid to DEWA directly."],
];
const TEXTS = [
  ["cheques", "Cheques", 'How the rent may be paid, e.g. "1 to 4 cheques, depending on the owner".'],
  ["chiller", "Chiller", "Whether the cooling is included in the rent."],
  ["documents", "Documents", "What a tenant brings. The assistant never asks for copies in the chat."],
];
// The fields that show their own message; every other residential_facts key belongs to the table.
const PLAIN_KEYS = new Set([
  `${PREFIX}.clusters`,
  `${PREFIX}.european_clusters`,
  ...[...NUMBERS, ...TEXTS].map(([key]) => `${PREFIX}.charges.${key}`),
]);
const GROUP_LABELS = {
  [PREFIX]: "Studios and one-bedrooms",
  [`${PREFIX}.rent`]: "Rent bands",
  [`${PREFIX}.sale`]: "Sale bands",
  [`${PREFIX}.charges`]: "Charges",
  [`${PREFIX}.charges.commission`]: "Commission",
};
const NUMBER = new Intl.NumberFormat("en-US");

function at(object, path) {
  return path.split(".").reduce((part, key) => (part && typeof part === "object" ? part[key] : undefined), object);
}

function money(value) {
  const n = Number(value);
  return value !== null && value !== undefined && value !== "" && Number.isFinite(n) ? NUMBER.format(n) : String(value ?? "");
}

function numberOf(value) {
  if (value === undefined || value === null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : value; // the server says what is wrong with it
}

function listOf(value) {
  const items = Array.isArray(value) ? value : String(value ?? "").split(",");
  return items.map((item) => String(item ?? "").trim()).filter(Boolean);
}

/**
 * The facts in the one shape the form sends, read through `get(path)`: from the stored facts or
 * from the inputs, so an untouched form compares equal and sends nothing.
 */
function shape(get) {
  const band = (path, keys) => Object.fromEntries(keys.map((key) => [key, numberOf(get(`${path}.${key}`))]));
  const bands = Object.fromEntries(BAND_ROWS.map(([path, , keys]) => [path, band(path, keys)]));
  const text = (key) => String(get(`charges.${key}`) ?? "").trim();
  return {
    clusters: listOf(get("clusters")),
    european_clusters: listOf(get("european_clusters")),
    rent: { studio: bands["rent.studio"], one_br: bands["rent.one_br"], one_br_european: bands["rent.one_br_european"] },
    sale: { studio: bands["sale.studio"], studio_morocco: bands["sale.studio_morocco"], one_br: bands["sale.one_br"] },
    charges: {
      deposit: bands["charges.deposit"],
      commission: { studio: bands["charges.commission.studio"], one_br: bands["charges.commission.one_br"] },
      ...Object.fromEntries(NUMBERS.map(([key]) => [key, numberOf(get(`charges.${key}`))])),
      ...Object.fromEntries(TEXTS.map(([key]) => [key, text(key)])),
    },
  };
}

function storedFacts(data) {
  const facts = data && typeof data.residential_facts === "object" && data.residential_facts ? data.residential_facts : {};
  return shape((path) => at(facts, path));
}

function bandText(band, keys) {
  const range = `AED ${money(band.from)}–${money(band.to)}`;
  return keys.includes("average") && band.average !== null ? [range, `AED ${money(band.average)}`] : [range, ""];
}

/** The studios and one-bedrooms facts as read-only rows, for an agent who cannot change the settings. */
export function residentialValues(data) {
  const facts = storedFacts(data);
  const rows = BAND_ROWS.map(([path, label, keys]) => {
    const [range, average] = bandText(at(facts, path) || {}, keys);
    return el("tr", {}, [el("th", { scope: "row" }, [label]), el("td", {}, [range]), el("td", {}, [average])]);
  });
  const charges = facts.charges;
  return el("div.lai-res", {}, [
    el("dl.lai-set__grid", {}, [
      el("dt", {}, ["Clusters"]),
      el("dd", {}, [facts.clusters.join(", ") || "None"]),
      el("dt", {}, ["European clusters"]),
      el("dd", {}, [facts.european_clusters.join(", ") || "None"]),
      el("dt", {}, ["VAT on the commission"]),
      el("dd", {}, [charges.vat_percent === null ? "Not set" : `${money(charges.vat_percent)}%`]),
      el("dt", {}, ["Ejari"]),
      el("dd", {}, [charges.ejari === null ? "Not set" : `AED ${money(charges.ejari)}`]),
      el("dt", {}, ["DEWA deposit"]),
      el("dd", {}, [charges.dewa_deposit === null ? "Not set" : `AED ${money(charges.dewa_deposit)}`]),
      ...TEXTS.flatMap(([key, label]) => [el("dt", {}, [label]), el("dd", {}, [charges[key] || "Not set"])]),
    ]),
    el("div.lai-res__scroll", {}, [
      el("table.lai-res__table", {}, [
        el("thead", {}, [el("tr", {}, ["Band", "Range", "Average"].map((title) => el("th", { scope: "col" }, [title])))]),
        el("tbody", {}, rows),
      ]),
    ]),
  ]);
}

/**
 * The editable studios and one-bedrooms part of the settings form.
 *
 * @returns {{ node: HTMLElement | null, changes: () => object, showError: (key: string, message: string) => HTMLElement | null, clearErrors: () => void }}
 *   changes() gives { residential_facts } only when a value differs from `data`, and then the whole
 *   object (the server checks it as one); showError() marks the input a server error names and
 *   returns it (null when it names none here). A server that sends no residential_facts (older than
 *   this screen) gets no fieldset and nothing is sent for it.
 */
export function residentialForm(data) {
  if (!data || typeof data.residential_facts !== "object" || !data.residential_facts) {
    return { node: null, changes: () => ({}), showError: () => null, clearErrors: () => {} };
  }
  const stored = storedFacts(data);
  const inputs = new Map(); // error key -> input
  const messages = new Map(); // error key -> message
  const errorList = el("ul.lai-res__errors", { hidden: true, role: "alert" });

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

  function field(path, label, hint, value, { type = "text", max = 300 } = {}) {
    const key = `${PREFIX}.${path}`;
    const id = `lai-res-${path.replace(/\W+/g, "-")}`;
    const props =
      type === "number"
        ? { id, type, value, min: 1, step: 1, inputMode: "numeric", autocomplete: "off", "aria-describedby": `${id}-hint` }
        : { id, type, value, maxLength: max, autocomplete: "off", "aria-describedby": `${id}-hint` };
    const input = track(key, el(`input.lai-set__input${type === "number" ? ".lai-res__num" : ""}`, props));
    return el("div.lai-set__field", {}, [
      el("label.lai-set__label", { for: id }, [label]),
      input,
      el("div.lai-set__hint", { id: `${id}-hint` }, [hint]),
    ]);
  }

  const body = el(
    "tbody",
    {},
    BAND_ROWS.map(([path, label, keys]) =>
      el("tr", {}, [
        el("th", { scope: "row" }, [label]),
        ...COLUMNS.map(([key, title]) => {
          if (!keys.includes(key)) return el("td", {}, []);
          const value = at(stored, `${path}.${key}`);
          return el("td", {}, [
            track(
              `${PREFIX}.${path}.${key}`,
              el("input.lai-set__input.lai-res__num", {
                type: "number",
                min: 1,
                step: 1,
                inputMode: "numeric",
                value: value === null || value === undefined ? "" : String(value),
                "aria-label": `${label}: ${title.toLowerCase()}`,
              })
            ),
          ]);
        }),
      ])
    )
  );
  const table = el("table.lai-res__table", {}, [
    el("thead", {}, [
      el("tr", {}, [el("th", { scope: "col" }, ["Band (AED)"]), ...COLUMNS.map(([, title]) => el("th", { scope: "col" }, [title]))]),
    ]),
    body,
  ]);

  const node = el("fieldset.lai-res", {}, [
    el("legend.lai-res__legend", {}, ["International City — studios and one-bedrooms"]),
    el("p.lai-set__hint", {}, [
      "What the assistant may quote in a chat about renting or buying a studio or a one-bedroom: rents per year and " +
        "prices in AED. It quotes only the band of the unit the customer asked about, and never any other figure.",
    ]),
    field("clusters", "Clusters", "The International City clusters with studios and one-bedrooms, separated by commas (at most 12).", stored.clusters.join(", ")),
    field(
      "european_clusters",
      "European clusters",
      "Where a one-bedroom rents at the European band. Each must be one of the clusters above.",
      stored.european_clusters.join(", ")
    ),
    el("div.lai-res__scroll", {}, [table]),
    errorList,
    el(
      "div.lai-res__trio",
      {},
      NUMBERS.map(([key, label, hint]) =>
        field(`charges.${key}`, label, hint, stored.charges[key] === null ? "" : String(stored.charges[key]), { type: "number" })
      )
    ),
    ...TEXTS.map(([key, label, hint]) => field(`charges.${key}`, label, hint, stored.charges[key])),
  ]);

  function isTableKey(key) {
    return key.startsWith(PREFIX) && !PLAIN_KEYS.has(key);
  }

  function errorLabel(key) {
    if (GROUP_LABELS[key]) return GROUP_LABELS[key];
    const row = BAND_ROWS.find(([path]) => key.startsWith(`${PREFIX}.${path}.`) || key === `${PREFIX}.${path}`);
    if (!row) return GROUP_LABELS[PREFIX];
    const column = COLUMNS.find(([name]) => key === `${PREFIX}.${row[0]}.${name}`);
    return column ? `${row[1]} · ${column[1]}` : row[1];
  }

  function drawErrors() {
    errorList.replaceChildren(
      ...[...messages.entries()].filter(([key]) => isTableKey(key)).map(([key, message]) => el("li", {}, [`${errorLabel(key)}: ${message}`]))
    );
    errorList.hidden = !errorList.childNodes.length;
  }

  function current() {
    return shape((path) => {
      const input = inputs.get(`${PREFIX}.${path}`);
      return input ? String(input.value ?? "").trim() : "";
    });
  }

  return {
    node,
    changes() {
      const next = current();
      return JSON.stringify(next) === JSON.stringify(stored) ? {} : { residential_facts: next };
    },
    showError(key, message) {
      const input = inputs.get(key) || (isTableKey(key) ? table : null);
      if (!input) return null;
      messages.set(key, String(message));
      input.setAttribute("aria-invalid", "true");
      if (!isTableKey(key)) {
        // A plain field shows its message under itself, like the rest of the form.
        const fieldNode = input.closest?.(".lai-set__field");
        let error = fieldNode?.querySelector?.(".lai-set__err");
        if (fieldNode && !error) {
          error = el("div.lai-set__err");
          fieldNode.append(error);
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
      table.removeAttribute("aria-invalid");
      for (const [key, input] of inputs) {
        input.removeAttribute("aria-invalid");
        if (!isTableKey(key)) {
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
