/**
 * Excel campaigns — one sheet, many numbers.
 *
 * The single-number Campaign screen stays exactly as it is. This one is for
 * the three-thousand-row sheet: upload it, say which column is the phone and
 * which column (or one fixed value) fills each {{n}}, tick the numbers to send
 * from and how many each may take, say where the CRM cards go — and start.
 * The server splits the rows into one campaign per number, the worker runs
 * them side by side, and this window can be closed at any point.
 *
 * Own files, own prefix (bc-), own endpoints (/api/campaigns/bulk/…). The
 * menu entry is injected from here rather than from inbox.js, the way
 * extras.js adds its theme rows, so the shared inbox module is untouched.
 */

import { bulkCampaigns, catalog, inbox } from "../api/api.js";
import { clear, debounce, el, formatBytes, modal, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";

const PLACEHOLDER = /\{\{(\d+)\}\}/g;
const MEDIA_HEADERS = { IMAGE: "image", VIDEO: "video", DOCUMENT: "document" };
const ACCEPT = {
  IMAGE: "image/jpeg,image/png",
  VIDEO: "video/mp4,video/3gpp",
  DOCUMENT: ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt",
};
const DEFAULT_CAP = 300;
const MAX_CAP = 500;
/** The select value meaning "type one value for everyone". */
const FIXED = "__fixed__";
const NONE = "";

const CRM_OPTIONS = [
  {
    value: "none",
    label: "No CRM card",
    hint: "Only the WhatsApp message goes out. Chats still appear in the inbox.",
  },
  {
    value: "owner_data",
    label: "Owner Data — calling board",
    hint: "A card already carrying the number is reused; otherwise one is created in New Data (category 13).",
  },
  {
    value: "availability",
    label: "Availability",
    hint: "A card already carrying the number is reused; otherwise one is created as New Availability (category 14).",
  },
];

/* ---------------------------------------------------------------- helpers */

function placeholdersIn(text) {
  const found = new Set();
  String(text || "").replace(PLACEHOLDER, (_, n) => found.add(n));
  return [...found].sort((a, b) => Number(a) - Number(b));
}

/** Template text with values in it; an unfilled {{n}} stays visible and tinted. */
function withValues(text, values) {
  const frag = document.createDocumentFragment();
  const source = String(text || "");
  let cursor = 0;
  PLACEHOLDER.lastIndex = 0;
  for (let match; (match = PLACEHOLDER.exec(source)); ) {
    if (match.index > cursor) frag.append(document.createTextNode(source.slice(cursor, match.index)));
    const value = String(values?.[match[1]] || "").trim();
    frag.append(value ? document.createTextNode(value) : el("span.bc-hole", {}, [match[0]]));
    cursor = match.index + match[0].length;
  }
  if (cursor < source.length) frag.append(document.createTextNode(source.slice(cursor)));
  return frag;
}

function field(label, control, hint) {
  return el("div.bc-field", {}, [
    el("span.bc-field__label", {}, [label]),
    control,
    hint ? el("span.bc-field__hint", {}, [hint]) : null,
  ]);
}

function card(step, title, sub, children) {
  return el("section.bc-card", {}, [
    el("header.bc-card__head", {}, [
      el("span.bc-step", {}, [String(step)]),
      el("div", {}, [el("h3.bc-card__title", {}, [title]), sub ? el("p.bc-card__sub", {}, [sub]) : null]),
    ]),
    ...children,
  ]);
}

function columnLabel(column) {
  const sample = column.samples?.[0] ? ` — e.g. ${column.samples[0]}` : "";
  return `${column.letter} · ${column.header}${sample}`;
}

function numberLabel(n) {
  const phone = String(n.phone_number || "").trim();
  const name = String(n.title || n.label || "").trim();
  if (phone && name && name !== phone) return `+${phone} · ${name}`;
  return name || (phone ? `+${phone}` : `#${n.id}`);
}

function numberMatches(n, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  const digits = q.replace(/\D/g, "");
  const phone = String(n.phone_number || "");
  const name = String(n.title || n.label || "").toLowerCase();
  const login = String(n.account_username || "").toLowerCase();
  return name.includes(q) || login.includes(q) || (digits && phone.includes(digits));
}

function statusWord(status) {
  return (
    {
      running: "Running",
      done: "Done",
      failed: "Failed",
      cancelled: "Cancelled",
      empty: "Empty",
      queued: "Queued",
      retrying: "Retrying",
      draft: "Draft",
    }[status] || status || "—"
  );
}

function crmWord(value) {
  return CRM_OPTIONS.find((o) => o.value === value)?.label || "No CRM card";
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function progressBar(done, total) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const fill = el("div.bc-bar__fill");
  fill.style.width = `${pct}%`;
  return { node: el("div.bc-bar", {}, [fill]), pct };
}

/* ------------------------------------------------------------------ modal */

export function openBulkCampaignModal() {
  const state = {
    file: null,
    sheet: null, // inspect result: {columns, rows, has_header, guesses}
    numbers: [],
    templates: [], // grouped by name+language
    template: null,
    mapping: { phone: null, name: null, vars: {} }, // vars: {"1": {column} | {value}}
    headerText: {},
    buttonVars: {},
    headerMedia: null, // {file, name, size, previewUrl}
    picked: [], // number ids, in the order they were ticked
    cap: DEFAULT_CAP,
    crmTarget: "none",
    preview: null, // {stats, warnings, sample, plan}
    previewSeq: 0,
    previewing: false,
    starting: false,
    tab: "new",
    batches: [],
    activeBatchId: null,
    pollTimer: null,
    listTimer: null,
  };

  /* ---- step 1: the file -------------------------------------------- */

  const fileInput = el("input", { type: "file", accept: ".xlsx,.xlsm,.csv,text/csv", hidden: true });
  const fileName = el("span.bc-file__name", {}, ["No file chosen"]);
  const fileClear = el("button.btn.btn--ghost.btn--sm", { type: "button", hidden: true }, ["Clear"]);
  const columnsBox = el("div.bc-cols", { hidden: true });
  const fileCard = card(1, "Excel file", "Any layout — you say which column is which in step 3.", [
    el("div.bc-file", {}, [
      el("button.btn.btn--primary.btn--sm", { type: "button", onclick: () => fileInput.click() }, [
        icon("folder", { size: 14 }),
        " Upload Excel or CSV",
      ]),
      fileName,
      fileClear,
      fileInput,
    ]),
    columnsBox,
  ]);

  /* ---- step 2: the template ---------------------------------------- */

  const templateSelect = el("select.field", {}, [el("option", { value: "" }, ["Loading templates…"])]);
  const templateNote = el("p.bc-note", { hidden: true });
  const templateCard = card(2, "Template", "The same template name must be approved on each number's business account.", [
    field("Approved template", templateSelect),
    templateNote,
  ]);

  /* ---- step 3: columns → template ----------------------------------- */

  const mapBox = el("div.bc-map");
  const mapCard = card(3, "Columns → template", "Which column is the phone, and what fills each {{n}}.", [mapBox]);

  /* ---- step 4: numbers ---------------------------------------------- */

  const numberSearch = el("input.field", { type: "search", placeholder: "Search number, name or login…", autocomplete: "off" });
  const selectAll = el("input", { type: "checkbox" });
  const numberList = el("div.bc-numlist");
  const capInput = el("input.field.bc-cap", { type: "number", min: "1", max: String(MAX_CAP), step: "1", value: String(DEFAULT_CAP) });
  const capacityLine = el("p.bc-capacity", {}, ["Tick the numbers to send from."]);
  const planBox = el("div.bc-plan");
  const numbersCard = card(4, "Numbers", "Rows are handed out in the order you tick, up to the cap each.", [
    el("div.bc-numhead", {}, [numberSearch, el("label.bc-check", {}, [selectAll, " Select all shown"])]),
    numberList,
    el("div.bc-caprow", {}, [
      field("Max rows per number", capInput, `Up to ${MAX_CAP}. Meta's own daily limit per number still applies.`),
      capacityLine,
    ]),
    planBox,
  ]);

  /* ---- step 5: CRM cards -------------------------------------------- */

  const crmBox = el("div.bc-crm");
  for (const option of CRM_OPTIONS) {
    const radio = el("input", { type: "radio", name: "bc-crm", value: option.value, checked: option.value === state.crmTarget });
    radio.addEventListener("change", () => {
      if (radio.checked) state.crmTarget = option.value;
    });
    crmBox.append(
      el("label.bc-crm__row", {}, [
        radio,
        el("span.bc-crm__text", {}, [el("strong", {}, [option.label]), el("span", {}, [option.hint])]),
      ])
    );
  }
  const crmCard = card(5, "CRM cards", "Decided here, per campaign. Nothing chosen means no card anywhere.", [crmBox]);

  /* ---- name, errors, actions ---------------------------------------- */

  const nameInput = el("input.field", { type: "text", placeholder: "e.g. Owners list — September", autocomplete: "off" });
  const errorBox = el("div.bc-error", { hidden: true });
  const statusBox = el("div.bc-status");
  const startBtn = el("button.btn.btn--primary", { type: "button", disabled: true }, ["Start campaign"]);

  /* ---- right column -------------------------------------------------- */

  const summaryBox = el("div.bc-summary", {}, [
    el("div.bc-summary__empty", {}, ["Upload a file, pick a template and map the columns to see the recipients."]),
  ]);
  const bubble = el("div.bc-bubble.is-empty");
  const bubbleButtons = el("div.bc-btns");
  const phonePreview = el("div.bc-phone", {}, [
    el("div.bc-phone__bar", {}, [
      el("div.bc-phone__avatar"),
      el("div.bc-phone__who", {}, [
        el("div.bc-phone__name", {}, ["First row"]),
        el("div.bc-phone__sub", {}, ["as the customer will see it"]),
      ]),
    ]),
    el("div.bc-phone__screen", {}, [el("div.bc-out", {}, [bubble, bubbleButtons])]),
  ]);

  const left = el("div.bc-left", {}, [
    el("div.bc-intro", {}, [
      el("div.bc-intro__kicker", {}, ["Official API · Excel"]),
      el("p.bc-intro__text", {}, [
        "One sheet, many numbers. Each number gets its own share and they all run in the background — close this window whenever you like.",
      ]),
    ]),
    fileCard,
    templateCard,
    mapCard,
    numbersCard,
    crmCard,
    card(6, "Name", "Optional — the batch and each number's share are named from it.", [field("Campaign name", nameInput)]),
    errorBox,
    statusBox,
  ]);

  const right = el("div.bc-right", {}, [
    el("div.bc-right__head", {}, [
      el("div.bc-right__title", {}, ["Recipients & preview"]),
      el("p.bc-right__hint", {}, ["Counts update as you map columns and tick numbers."]),
    ]),
    summaryBox,
    phonePreview,
  ]);

  const actionsBar = el("div.bc-actions", {}, [
    el("p.bc-actions__hint", {}, ["Sending continues on the server after you close this — open Batches to watch."]),
    el("div.bc-actions__btns", {}, [
      el("button.btn.btn--ghost", { type: "button", onclick: () => setTab("batches") }, ["Batches"]),
      startBtn,
    ]),
  ]);

  const newPane = el("div.bc-pane.is-active", {}, [el("div.bc-main", {}, [left, right]), actionsBar]);

  /* ---- batches pane -------------------------------------------------- */

  const batchList = el("div.bc-batches__list");
  const batchDetail = el("div.bc-batches__detail");
  const batchesPane = el("div.bc-pane.bc-batches", { hidden: true }, [
    el("aside.bc-batches__aside", {}, [
      el("div.bc-batches__head", {}, [
        el("h3.bc-batches__heading", {}, ["Excel campaigns"]),
        el("p.bc-batches__blurb", {}, ["One row per upload · each number's share underneath"]),
      ]),
      batchList,
    ]),
    batchDetail,
  ]);

  const tabNew = el("button.bc-tab.is-active", { type: "button", role: "tab" }, ["New Excel campaign"]);
  const tabBatches = el("button.bc-tab", { type: "button", role: "tab" }, ["Batches"]);
  const titleEl = el("span", {}, ["Excel campaign"]);
  const shell = el("div.bc-shell", {}, [el("div.bc-tabs", { role: "tablist" }, [tabNew, tabBatches]), newPane, batchesPane]);

  const dialog = modal(titleEl, shell, {
    wide: true,
    onClose: () => {
      if (state.pollTimer) clearInterval(state.pollTimer);
      if (state.listTimer) clearInterval(state.listTimer);
      if (state.headerMedia?.previewUrl) URL.revokeObjectURL(state.headerMedia.previewUrl);
    },
  });
  dialog.box.classList.add("modal__box--bulk");

  function setTab(which) {
    state.tab = which;
    const isNew = which === "new";
    tabNew.classList.toggle("is-active", isNew);
    tabBatches.classList.toggle("is-active", !isNew);
    newPane.hidden = !isNew;
    batchesPane.hidden = isNew;
    newPane.classList.toggle("is-active", isNew);
    batchesPane.classList.toggle("is-active", !isNew);
    titleEl.textContent = isNew ? "Excel campaign" : "Excel campaigns";
    if (!isNew) {
      loadBatches();
      if (!state.listTimer) state.listTimer = setInterval(() => state.tab === "batches" && loadBatches({ quiet: true }), 5000);
    } else if (state.listTimer) {
      clearInterval(state.listTimer);
      state.listTimer = null;
    }
  }
  tabNew.addEventListener("click", () => setTab("new"));
  tabBatches.addEventListener("click", () => setTab("batches"));

  /* ---- the file ------------------------------------------------------ */

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0] || null;
    fileInput.value = "";
    if (!file) return;
    state.file = file;
    state.sheet = null;
    fileName.textContent = `${file.name} · ${formatBytes(file.size)}`;
    fileClear.hidden = false;
    clear(columnsBox).append(el("span.bc-cols__note", {}, ["Reading the sheet…"]));
    columnsBox.hidden = false;
    try {
      state.sheet = await bulkCampaigns.inspect(file);
      renderColumns();
      applyGuesses();
    } catch (err) {
      state.file = null;
      fileName.textContent = "No file chosen";
      fileClear.hidden = true;
      columnsBox.hidden = true;
      showError(err?.message || "Could not read that file.");
    }
    renderMapping();
    schedulePreview();
  });

  fileClear.addEventListener("click", () => {
    state.file = null;
    state.sheet = null;
    state.preview = null;
    fileName.textContent = "No file chosen";
    fileClear.hidden = true;
    columnsBox.hidden = true;
    renderMapping();
    renderSummary();
    refreshStartState();
  });

  function renderColumns() {
    clear(columnsBox);
    const sheet = state.sheet;
    if (!sheet) return;
    columnsBox.append(
      el("div.bc-cols__head", {}, [
        el("strong", {}, [`${sheet.rows} row${sheet.rows === 1 ? "" : "s"}`]),
        ` · ${sheet.columns.length} column${sheet.columns.length === 1 ? "" : "s"}`,
        sheet.has_header ? "" : " · no header row — columns are named by letter",
      ]),
      el(
        "div.bc-cols__chips",
        {},
        sheet.columns.map((column) =>
          el("span.bc-col", { title: (column.samples || []).join(" · ") }, [
            el("b", {}, [column.letter]),
            ` ${column.header}`,
            column.samples?.[0] ? el("em", {}, [column.samples[0]]) : null,
          ])
        )
      )
    );
    columnsBox.hidden = false;
  }

  /** The server's guess at phone and name, applied only where nothing is chosen yet. */
  function applyGuesses() {
    const guesses = state.sheet?.guesses || {};
    if (state.mapping.phone === null && Number.isInteger(guesses.phone)) state.mapping.phone = guesses.phone;
    if (state.mapping.name === null && Number.isInteger(guesses.name)) state.mapping.name = guesses.name;
    const first = state.mapping.vars["1"];
    if (state.template?.variable_count > 0 && !first && Number.isInteger(guesses.name)) {
      state.mapping.vars["1"] = { column: guesses.name };
    }
  }

  /* ---- templates ------------------------------------------------------ */

  async function loadTemplates() {
    let rows = [];
    try {
      rows = await catalog.allTemplates();
    } catch (err) {
      toast(err?.message || "Could not load templates", "err");
    }
    const groups = new Map();
    for (const t of Array.isArray(rows) ? rows : []) {
      if (String(t.status || "").toUpperCase() !== "APPROVED") continue;
      const key = `${t.name}|${t.language || "en"}`;
      const group = groups.get(key) || { ...t, ids: [], wabas: new Set() };
      group.ids.push(t.id);
      if (t.waba_business_id) group.wabas.add(t.waba_business_id);
      groups.set(key, group);
    }
    state.templates = [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
    clear(templateSelect).append(el("option", { value: "" }, ["Select approved template…"]));
    for (const t of state.templates) {
      const bits = [t.name, t.language || "en"];
      if (t.variable_count) bits.push(`${t.variable_count} var${t.variable_count > 1 ? "s" : ""}`);
      if (t.requires_header_media) bits.push("media");
      if ((t.buttons || []).length) bits.push(`${t.buttons.length} btn`);
      bits.push(`on ${t.wabas.size} account${t.wabas.size === 1 ? "" : "s"}`);
      templateSelect.append(el("option", { value: `${t.name}|${t.language || "en"}` }, [bits.join(" · ")]));
    }
    if (!state.templates.length) {
      templateSelect.append(el("option", { value: "", disabled: true }, ["No approved templates on your numbers"]));
    }
  }

  templateSelect.addEventListener("change", () => {
    state.template = state.templates.find((t) => `${t.name}|${t.language || "en"}` === templateSelect.value) || null;
    state.mapping.vars = {};
    state.headerText = {};
    state.buttonVars = {};
    if (state.headerMedia?.previewUrl) URL.revokeObjectURL(state.headerMedia.previewUrl);
    state.headerMedia = null;
    applyGuesses();
    renderTemplateNote();
    renderMapping();
    renderPlan();
    schedulePreview();
  });

  function renderTemplateNote() {
    const t = state.template;
    if (!t) {
      templateNote.hidden = true;
      return;
    }
    const category = String(t.category || "").toUpperCase();
    clear(templateNote).append(
      el("strong", {}, [t.name]),
      ` · ${category || "template"} · approved on ${t.wabas.size} business account${t.wabas.size === 1 ? "" : "s"}. `,
      "Numbers whose account does not have it are skipped at start, with a note.",
      category.includes("MARKET")
        ? " MARKETING templates share Meta's per-customer daily cap — expect some cap failures on big lists."
        : ""
    );
    templateNote.hidden = false;
  }

  /* ---- mapping -------------------------------------------------------- */

  function columnSelect(current, { allowNone = false, allowFixed = false, onChange }) {
    const select = el("select.field.bc-map__select");
    select.append(el("option", { value: NONE }, [allowNone ? "— none —" : "Choose a column…"]));
    for (const column of state.sheet?.columns || []) {
      select.append(el("option", { value: String(column.index) }, [columnLabel(column)]));
    }
    if (allowFixed) select.append(el("option", { value: FIXED }, ["Same value for everyone…"]));
    select.value = current === null || current === undefined ? NONE : String(current);
    if (select.value !== String(current ?? NONE) && current !== null && current !== undefined) select.value = NONE;
    select.addEventListener("change", () => onChange(select.value));
    return select;
  }

  function renderMapping() {
    clear(mapBox);
    const t = state.template;
    if (!state.sheet || !t) {
      mapBox.append(
        el("div.bc-empty", {}, [
          !state.sheet && !t
            ? "Upload the file and pick a template first."
            : !state.sheet
              ? "Upload the file to see its columns."
              : "Pick a template to see what it needs.",
        ])
      );
      return;
    }

    mapBox.append(
      el("div.bc-map__row.bc-map__row--key", {}, [
        el("span.bc-map__label", {}, ["Phone number"]),
        columnSelect(state.mapping.phone, {
          onChange: (value) => {
            state.mapping.phone = value === NONE ? null : Number(value);
            schedulePreview();
          },
        }),
      ]),
      el("div.bc-map__row", {}, [
        el("span.bc-map__label", {}, ["Name", el("small", {}, ["chat + CRM card"])]),
        columnSelect(state.mapping.name, {
          allowNone: true,
          onChange: (value) => {
            state.mapping.name = value === NONE ? null : Number(value);
            schedulePreview();
          },
        }),
      ])
    );

    for (const n of placeholdersIn(t.body_text)) {
      const entry = state.mapping.vars[n] || {};
      const isFixed = Object.prototype.hasOwnProperty.call(entry, "value");
      const fixedInput = el("input.field.bc-map__fixed", {
        type: "text",
        placeholder: "Text used for every row",
        value: isFixed ? entry.value : "",
        hidden: !isFixed,
      });
      fixedInput.addEventListener("input", () => {
        state.mapping.vars[n] = { value: fixedInput.value };
        renderPhonePreview();
        schedulePreview();
      });
      const select = columnSelect(isFixed ? FIXED : Number.isInteger(entry.column) ? entry.column : null, {
        allowFixed: true,
        onChange: (value) => {
          if (value === FIXED) {
            state.mapping.vars[n] = { value: fixedInput.value };
            fixedInput.hidden = false;
            fixedInput.focus();
          } else {
            fixedInput.hidden = true;
            if (value === NONE) delete state.mapping.vars[n];
            else state.mapping.vars[n] = { column: Number(value) };
          }
          schedulePreview();
        },
      });
      mapBox.append(
        el("div.bc-map__row", {}, [
          el("span.bc-map__label", {}, [`{{${n}}}`, el("small", {}, [contextFor(t.body_text, n)])]),
          el("div.bc-map__cell", {}, [select, fixedInput]),
        ])
      );
    }

    const header = t.header;
    if (t.requires_header_media) {
      mapBox.append(mediaRow(header.format));
    } else if (header?.format === "TEXT") {
      for (const n of placeholdersIn(header.text)) {
        mapBox.append(
          textRow(`Header {{${n}}}`, "Same text for every row", state.headerText[n] || "", (value) => {
            state.headerText[n] = value;
            renderPhonePreview();
            refreshStartState();
          })
        );
      }
    }
    for (const button of t.buttons || []) {
      if (!button.variable_count) continue;
      mapBox.append(
        textRow(`Link for “${button.text || "Button"}”`, "Appended to the approved URL", state.buttonVars[String(button.index)] || "", (value) => {
          state.buttonVars[String(button.index)] = value;
          refreshStartState();
        })
      );
    }
    if (!placeholdersIn(t.body_text).length && !t.requires_header_media) {
      mapBox.append(el("p.bc-note", {}, ["This template has no body fields — only the phone column is needed."]));
    }
  }

  /** The few words around a placeholder, so "{{2}}" reads as "…viewing at ▮ on…". */
  function contextFor(text, n) {
    const source = String(text || "");
    const at = source.indexOf(`{{${n}}}`);
    if (at === -1) return "";
    const before = source.slice(Math.max(0, at - 22), at).trimStart();
    const after = source.slice(at + `{{${n}}}`.length, at + `{{${n}}}`.length + 14).trimEnd();
    return `…${before}▮${after}…`.replace(/\s+/g, " ");
  }

  function textRow(label, placeholder, value, onInput) {
    const input = el("input.field", { type: "text", placeholder, value, autocomplete: "off" });
    input.addEventListener("input", () => onInput(input.value));
    return el("div.bc-map__row", {}, [el("span.bc-map__label", {}, [label]), input]);
  }

  function mediaRow(format) {
    const kind = MEDIA_HEADERS[format] || "file";
    const picker = el("input", { type: "file", accept: ACCEPT[format] || "", hidden: true });
    const status = el("span.bc-media__status", {}, [
      state.headerMedia ? `${state.headerMedia.name} · ${formatBytes(state.headerMedia.size)}` : `Choose the ${kind} — it is uploaded to every number at start.`,
    ]);
    picker.addEventListener("change", () => {
      const file = picker.files?.[0];
      picker.value = "";
      if (!file) return;
      if (state.headerMedia?.previewUrl) URL.revokeObjectURL(state.headerMedia.previewUrl);
      state.headerMedia = {
        file,
        name: file.name,
        size: file.size,
        previewUrl: format === "IMAGE" ? URL.createObjectURL(file) : "",
      };
      status.textContent = `${file.name} · ${formatBytes(file.size)}`;
      renderPhonePreview();
      refreshStartState();
    });
    return el("div.bc-map__row", {}, [
      el("span.bc-map__label", {}, [`${kind[0].toUpperCase()}${kind.slice(1)} header`]),
      el("div.bc-media", {}, [
        el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: () => picker.click() }, [`Choose ${kind}`]),
        status,
        picker,
      ]),
    ]);
  }

  /* ---- numbers -------------------------------------------------------- */

  async function loadNumbers() {
    try {
      const data = await catalog.numbers();
      state.numbers = Array.isArray(data) ? data : data?.numbers || [];
    } catch (err) {
      toast(err?.message || "Could not load numbers", "err");
      state.numbers = [];
    }
    renderNumbers();
  }

  function renderNumbers() {
    clear(numberList);
    const query = numberSearch.value;
    let shown = 0;
    for (const n of state.numbers) {
      if (!numberMatches(n, query)) continue;
      shown += 1;
      const box = el("input", { type: "checkbox", checked: state.picked.includes(n.id), "data-id": String(n.id) });
      box.addEventListener("change", () => {
        if (box.checked) {
          if (!state.picked.includes(n.id)) state.picked.push(n.id);
        } else {
          state.picked = state.picked.filter((id) => id !== n.id);
        }
        syncSelectAll();
        renderCapacity();
        schedulePreview();
      });
      numberList.append(
        el("label.bc-num", { class: n.send_blocked ? "is-blocked" : "" }, [
          box,
          el("span.bc-num__text", {}, [
            el("span.bc-num__phone", {}, [`+${n.phone_number || ""}`]),
            el("span.bc-num__name", {}, [
              [n.title !== n.phone_number ? n.title : "", n.account_username].filter(Boolean).join(" · ") || "",
              n.send_blocked ? " — banned by the provider" : "",
            ]),
          ]),
          n.template_count === 0 ? el("span.bc-num__tag", {}, ["no templates"]) : null,
        ])
      );
    }
    if (!shown) numberList.append(el("div.bc-empty", {}, [state.numbers.length ? "No number matches that search." : "No numbers on your profile."]));
    syncSelectAll();
    renderCapacity();
  }

  function shownIds() {
    return [...numberList.querySelectorAll('input[type="checkbox"]')].map((box) => Number(box.dataset.id));
  }

  function syncSelectAll() {
    const ids = shownIds();
    selectAll.checked = ids.length > 0 && ids.every((id) => state.picked.includes(id));
  }

  selectAll.addEventListener("change", () => {
    const ids = shownIds();
    if (selectAll.checked) {
      for (const id of ids) if (!state.picked.includes(id)) state.picked.push(id);
    } else {
      state.picked = state.picked.filter((id) => !ids.includes(id));
    }
    renderNumbers();
    schedulePreview();
  });

  numberSearch.addEventListener("input", debounce(renderNumbers, 120));

  capInput.addEventListener("input", () => {
    state.cap = Math.max(1, Math.min(MAX_CAP, Number(capInput.value) || DEFAULT_CAP));
    renderCapacity();
    schedulePreview();
  });
  // Typed 900? The box shows the 500 that will actually be used.
  capInput.addEventListener("change", () => {
    capInput.value = String(state.cap);
  });

  function renderCapacity() {
    const count = state.picked.length;
    const rows = state.preview?.stats?.valid ?? state.sheet?.rows ?? 0;
    if (!count) {
      capacityLine.textContent = "Tick the numbers to send from.";
      return;
    }
    const capacity = count * state.cap;
    let text = `${count} number${count === 1 ? "" : "s"} × ${state.cap} = room for ${capacity} rows`;
    if (rows) text += rows > capacity ? ` — ${rows - capacity} of ${rows} rows would be left out` : ` · ${rows} rows fit`;
    capacityLine.textContent = text + ".";
  }

  function renderPlan() {
    clear(planBox);
    const plan = state.preview?.plan;
    if (!plan) return;
    const lanes = plan.lanes || [];
    const skipped = plan.skipped_numbers || [];
    if (!lanes.length && !skipped.length) return;
    const table = el("table.bc-plan__table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", {}, ["Number"]), el("th", {}, ["Rows"]), el("th", {}, ["Template"])])]),
      el(
        "tbody",
        {},
        lanes.map((lane) =>
          el("tr", { class: lane.count ? "" : "is-idle" }, [
            el("td", {}, [`+${lane.phone}`, lane.label && lane.label !== lane.phone ? el("small", {}, [lane.label]) : null]),
            el("td", {}, [lane.count ? `${lane.count}` : "0", lane.count ? el("small", {}, [`rows ${lane.first_row}–${lane.last_row}`]) : null]),
            el("td.is-ok", {}, ["approved"]),
          ])
        )
      ),
    ]);
    planBox.append(table);
    if (skipped.length) {
      planBox.append(
        el("div.bc-plan__skipped", {}, [
          el("strong", {}, [`${skipped.length} ticked number${skipped.length === 1 ? "" : "s"} will be skipped: `]),
          skipped.map((s) => `+${s.phone || s.number_id} — ${s.reason}`).join(" · "),
        ])
      );
    }
    if (plan.leftover) {
      planBox.append(
        el("div.bc-plan__leftover", {}, [
          el("strong", {}, [`${plan.leftover} rows have no number. `]),
          "Tick more numbers or raise the cap — otherwise they are not sent.",
        ])
      );
    }
  }

  /* ---- preview (server-side parse + split) ------------------------- */

  function mappingComplete() {
    const t = state.template;
    if (!t || state.mapping.phone === null) return false;
    for (const n of placeholdersIn(t.body_text)) {
      const entry = state.mapping.vars[n];
      if (!entry) return false;
      if (Object.prototype.hasOwnProperty.call(entry, "value") && !String(entry.value || "").trim()) return false;
    }
    return true;
  }

  const schedulePreview = debounce(refreshPreview, 450);

  async function refreshPreview() {
    if (!state.file || !state.template || !mappingComplete() || !state.picked.length) {
      state.preview = null;
      renderSummary();
      renderPlan();
      refreshStartState();
      return;
    }
    const seq = ++state.previewSeq;
    state.previewing = true;
    refreshStartState();
    try {
      const data = await bulkCampaigns.preview({
        file: state.file,
        template_id: state.template.ids[0],
        mapping: state.mapping,
        number_ids: state.picked,
        per_number_cap: state.cap,
      });
      if (seq !== state.previewSeq) return;
      state.preview = data;
      errorBox.hidden = true;
    } catch (err) {
      if (seq !== state.previewSeq) return;
      state.preview = null;
      showError(err?.message || "Could not read the sheet with that mapping.");
    } finally {
      if (seq === state.previewSeq) {
        state.previewing = false;
        renderSummary();
        renderPlan();
        renderCapacity();
        refreshStartState();
      }
    }
  }

  function renderSummary() {
    clear(summaryBox);
    const p = state.preview;
    if (!p) {
      summaryBox.append(
        el("div.bc-summary__empty", {}, [
          state.previewing
            ? "Reading the sheet…"
            : !state.file
              ? "Upload a file to begin."
              : !state.template
                ? "Pick a template."
                : !mappingComplete()
                  ? "Map the phone column and every {{n}}."
                  : "Tick at least one number.",
        ])
      );
      renderPhonePreview();
      return;
    }
    const s = p.stats || {};
    const plan = p.plan || {};
    summaryBox.append(
      el("div.bc-stats", {}, [
        stat(s.valid || 0, "recipients", "is-ok"),
        stat(plan.assigned || 0, "will send", "is-send"),
        stat(plan.leftover || 0, "left out", plan.leftover ? "is-bad" : ""),
        stat((s.invalid_phone || 0) + (s.duplicate || 0) + (s.empty_value || 0), "rows skipped", ""),
      ])
    );
    const drops = [];
    if (s.invalid_phone) drops.push(`${s.invalid_phone} without a valid phone`);
    if (s.duplicate) drops.push(`${s.duplicate} duplicate${s.duplicate === 1 ? "" : "s"}`);
    if (s.empty_value) drops.push(`${s.empty_value} with an empty value`);
    if (drops.length) summaryBox.append(el("p.bc-summary__drops", {}, [`Skipped: ${drops.join(", ")}.`]));
    if ((p.warnings || []).length) {
      summaryBox.append(el("ul.bc-warnings", {}, p.warnings.slice(0, 6).map((w) => el("li", {}, [w]))));
    }
    const sample = p.sample || [];
    if (sample.length) {
      summaryBox.append(
        el("div.bc-sample__title", {}, [`First ${sample.length} of ${s.valid}`]),
        el(
          "ul.bc-sample",
          {},
          sample.map((r) => {
            const vars = Object.entries(r.variables || {})
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([k, v]) => `{{${k}}} ${v}`)
              .join(" · ");
            return el("li", {}, [el("strong", {}, [`+${r.phone}`]), r.name ? ` ${r.name}` : "", vars ? el("span.bc-sample__vars", {}, [vars]) : null]);
          })
        )
      );
    }
    renderPhonePreview();
  }

  function stat(n, label, kind) {
    return el("div.bc-stat", { class: kind }, [el("span.bc-stat__n", {}, [String(n)]), el("span.bc-stat__l", {}, [label])]);
  }

  function renderPhonePreview() {
    const t = state.template;
    clear(bubble);
    clear(bubbleButtons);
    if (!t) {
      bubble.classList.add("is-empty");
      bubble.append(el("div.bc-bubble__hint", {}, ["The template appears here."]));
      return;
    }
    bubble.classList.remove("is-empty");
    const header = t.header;
    if (t.requires_header_media) {
      if (header?.format === "IMAGE" && state.headerMedia?.previewUrl) {
        bubble.append(el("img.bc-bubble__image", { src: state.headerMedia.previewUrl, alt: "" }));
      } else {
        bubble.append(
          el("div.bc-bubble__media", { class: state.headerMedia ? "" : "is-missing" }, [
            state.headerMedia ? `${state.headerMedia.name} · ${formatBytes(state.headerMedia.size)}` : `${MEDIA_HEADERS[header?.format] || "media"} header — not chosen yet`,
          ])
        );
      }
    } else if (header?.format === "TEXT" && header.text) {
      bubble.append(el("div.bc-bubble__header", {}, [withValues(header.text, state.headerText)]));
    }
    // The first parsed row when there is one; fixed values otherwise, so the
    // preview follows the mapping even before the server has answered.
    const values = state.preview?.sample?.[0]?.variables || fixedValues();
    bubble.append(el("div.bc-bubble__body", {}, [withValues(t.body_text, values)]));
    if (t.footer_text) bubble.append(el("div.bc-bubble__footer", {}, [t.footer_text]));
    bubble.append(el("div.bc-bubble__meta", {}, [new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })]));
    for (const button of (t.buttons || []).slice(0, 3)) {
      bubbleButtons.append(el("div.bc-btn", {}, [button.text || "Button"]));
    }
  }

  function fixedValues() {
    const out = {};
    for (const [n, entry] of Object.entries(state.mapping.vars)) {
      if (Object.prototype.hasOwnProperty.call(entry, "value")) out[n] = entry.value;
    }
    return out;
  }

  /* ---- start ---------------------------------------------------------- */

  function missing() {
    if (!state.file) return "Upload the Excel file.";
    if (!state.template) return "Pick an approved template.";
    if (state.mapping.phone === null) return "Choose the phone number column.";
    if (!mappingComplete()) return "Map every {{n}} to a column, or type one value for everyone.";
    const header = state.template.header;
    if (state.template.requires_header_media && !state.headerMedia?.file) {
      return `Choose the ${MEDIA_HEADERS[header?.format] || "media"} for the header.`;
    }
    if (header?.format === "TEXT" && placeholdersIn(header.text).some((n) => !(state.headerText[n] || "").trim())) {
      return "Fill in every header field.";
    }
    const button = (state.template.buttons || []).find((b) => b.variable_count && !(state.buttonVars[String(b.index)] || "").trim());
    if (button) return `Fill in the link for “${button.text}”.`;
    if (!state.picked.length) return "Tick at least one number.";
    if (state.previewing) return "Reading the sheet…";
    if (!state.preview) return "The sheet has not been read yet — check the mapping.";
    if (!(state.preview.plan?.assigned > 0)) return "No ticked number can take any rows.";
    return "";
  }

  function refreshStartState() {
    startBtn.disabled = state.starting || Boolean(missing());
  }

  function showError(text) {
    errorBox.textContent = text;
    errorBox.hidden = false;
  }

  startBtn.addEventListener("click", async () => {
    const blocked = missing();
    if (blocked) {
      showError(blocked);
      return;
    }
    const p = state.preview;
    const plan = p.plan;
    const lanes = (plan.lanes || []).filter((l) => l.count);
    const category = String(state.template.category || "").toUpperCase();
    const lines = [
      `Send “${state.template.name}” to ${plan.assigned} recipient${plan.assigned === 1 ? "" : "s"} from ${lanes.length} number${lanes.length === 1 ? "" : "s"} (up to ${plan.cap} each)?`,
      plan.leftover ? `${plan.leftover} rows have no number and will NOT be sent.` : "",
      (plan.skipped_numbers || []).length ? `${plan.skipped_numbers.length} ticked number(s) are skipped — see the plan.` : "",
      `CRM cards: ${crmWord(state.crmTarget)}.`,
      category.includes("MARKET") ? "MARKETING template — Meta's per-customer daily cap can fail some sends later; those are not retried." : "",
    ].filter(Boolean);
    if (!window.confirm(lines.join("\n\n"))) return;

    state.starting = true;
    refreshStartState();
    startBtn.textContent = "Starting…";
    errorBox.hidden = true;
    clear(statusBox).append(el("div.bc-empty", {}, ["Starting…"]));

    try {
      const headerMediaIds = {};
      if (state.template.requires_header_media && state.headerMedia?.file) {
        // Meta media ids belong to the number they were uploaded through, so
        // the one file goes up once per lane before anything is created.
        for (const lane of lanes) {
          clear(statusBox).append(el("div.bc-empty", {}, [`Uploading ${state.headerMedia.name} to +${lane.phone}…`]));
          const result = await inbox.uploadMedia(state.headerMedia.file, { numberId: lane.number_id }).promise;
          headerMediaIds[String(lane.number_id)] = result.media_id;
        }
      }
      const batch = await bulkCampaigns.create({
        file: state.file,
        template_id: state.template.ids[0],
        mapping: state.mapping,
        number_ids: state.picked,
        per_number_cap: state.cap,
        name: nameInput.value.trim(),
        crm_target: state.crmTarget,
        header_variables: { ...state.headerText },
        button_variables: { ...state.buttonVars },
        header_media_ids: headerMediaIds,
      });
      toast(`Started: ${batch.total} recipients across ${batch.lane_count} number${batch.lane_count === 1 ? "" : "s"}. Running in the background.`, "ok");
      clear(statusBox);
      state.activeBatchId = batch.id;
      setTab("batches");
      showBatch(batch.id);
      pollBatch(batch.id);
      startBtn.textContent = "Start another";
    } catch (err) {
      clear(statusBox);
      showError(err?.message || "Could not start.");
      toast(err?.message || "Could not start", "err");
      startBtn.textContent = "Start campaign";
    } finally {
      state.starting = false;
      refreshStartState();
    }
  });

  /* ---- batches --------------------------------------------------------- */

  function isLive(b) {
    return b?.status === "running";
  }

  async function loadBatches({ quiet = false } = {}) {
    if (!quiet) clear(batchList).append(el("div.bc-empty", {}, ["Loading…"]));
    let rows;
    try {
      rows = await bulkCampaigns.list();
    } catch (err) {
      if (!quiet) clear(batchList).append(el("div.bc-empty", {}, [err?.message || "Could not load."]));
      return;
    }
    state.batches = Array.isArray(rows) ? rows : [];
    renderBatchList();
    if (!quiet) {
      const prefer = state.batches.find((b) => b.id === state.activeBatchId) || state.batches.find(isLive) || state.batches[0];
      if (prefer) {
        showBatch(prefer.id);
        if (isLive(prefer)) pollBatch(prefer.id);
      } else {
        clear(batchDetail).append(el("div.bc-empty", {}, ["No Excel campaigns yet. Start one from the first tab."]));
      }
    }
  }

  function renderBatchList() {
    clear(batchList);
    if (!state.batches.length) {
      batchList.append(el("div.bc-empty", {}, ["No Excel campaigns yet."]));
      return;
    }
    for (const b of state.batches) {
      const c = b.counts || {};
      batchList.append(
        el("button.bc-batch", { type: "button", class: (b.id === state.activeBatchId ? "is-active " : "") + (isLive(b) ? "is-live" : ""), onclick: () => { showBatch(b.id); if (isLive(b)) pollBatch(b.id); } }, [
          el("div.bc-batch__top", {}, [el("strong", {}, [b.name || `#${b.id}`]), el("span.bc-badge", { class: `is-${b.status}` }, [statusWord(b.status)])]),
          el("div.bc-batch__chips", {}, [
            el("span.bc-chip.is-sent", {}, [`Sent ${c.sent || 0}`]),
            el("span.bc-chip.is-failed", {}, [`Failed ${c.failed || 0}`]),
            c.retrying ? el("span.bc-chip.is-retry", {}, [`Retry ${c.retrying}`]) : null,
            c.pending ? el("span.bc-chip", {}, [`Pending ${c.pending}`]) : null,
            el("span.bc-chip", {}, [`${b.total || 0} total`]),
          ]),
          el("span.bc-batch__sub", {}, [`${b.template_name} · ${b.lane_count} number${b.lane_count === 1 ? "" : "s"} · ${when(b.created_at)}`]),
        ])
      );
    }
  }

  async function showBatch(id) {
    state.activeBatchId = id;
    for (const node of batchList.querySelectorAll(".bc-batch")) node.classList.toggle("is-active", false);
    try {
      const full = await bulkCampaigns.get(id);
      renderBatchDetail(full);
      renderBatchList();
    } catch (err) {
      clear(batchDetail).append(el("div.bc-empty", {}, [err?.message || "Could not load this campaign."]));
    }
  }

  function renderBatchDetail(b) {
    clear(batchDetail);
    const c = b.counts || {};
    const settled = (c.sent || 0) + (c.failed || 0) + (c.skipped || 0);
    const bar = progressBar(settled, b.total || 0);
    const cancelBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["Stop remaining sends"]);
    cancelBtn.addEventListener("click", async () => {
      if (!window.confirm("Stop this Excel campaign? Rows not sent yet stay unsent.")) return;
      cancelBtn.disabled = true;
      try {
        renderBatchDetail(await bulkCampaigns.cancel(b.id));
        loadBatches({ quiet: true });
      } catch (err) {
        cancelBtn.disabled = false;
        toast(err?.message || "Could not stop", "err");
      }
    });

    batchDetail.append(
      el("div.bc-detail__head", {}, [
        el("div", {}, [
          el("h3.bc-detail__title", {}, [b.name || `#${b.id}`]),
          el("p.bc-detail__meta", {}, [
            `${b.template_name} · ${b.lane_count} number${b.lane_count === 1 ? "" : "s"} · up to ${b.per_number_cap} each · ${crmWord(b.crm_target)} · ${when(b.created_at)}`,
          ]),
        ]),
        el("div.bc-detail__actions", {}, [el("span.bc-badge.bc-badge--lg", { class: `is-${b.status}` }, [statusWord(b.status)]), isLive(b) ? cancelBtn : null]),
      ]),
      el("div.bc-progress", {}, [bar.node, el("div.bc-progress__meta", {}, [`${bar.pct}% · Sent ${c.sent || 0} · Failed ${c.failed || 0}${c.retrying ? ` · Retrying ${c.retrying}` : ""}${c.pending ? ` · Pending ${c.pending}` : ""}${c.skipped ? ` · Skipped ${c.skipped}` : ""} · Total ${b.total || 0}`])]),
      el("div.bc-stats", {}, [stat(c.sent || 0, "sent", "is-ok"), stat(c.failed || 0, "failed", c.failed ? "is-bad" : ""), stat(c.retrying || 0, "retrying", ""), stat(c.pending || 0, "pending", "")])
    );

    if (b.leftover) {
      batchDetail.append(el("div.bc-plan__leftover", {}, [el("strong", {}, [`${b.leftover} rows were left out `]), "— no number had room. Start another campaign for them."]));
    }
    if ((b.skipped_numbers || []).length) {
      batchDetail.append(
        el("div.bc-plan__skipped", {}, [
          el("strong", {}, ["Skipped numbers: "]),
          b.skipped_numbers.map((s) => `+${s.phone || s.number_id} — ${s.reason}`).join(" · "),
        ])
      );
    }

    batchDetail.append(el("div.bc-section__title", {}, ["Per number"]));
    const lanes = b.lanes || [];
    if (!lanes.length) {
      batchDetail.append(el("div.bc-empty", {}, ["No number took any rows."]));
    }
    for (const lane of lanes) {
      const done = (lane.sent || 0) + (lane.failed || 0) + (lane.skipped || 0);
      const laneBar = progressBar(done, lane.total || 0);
      batchDetail.append(
        el("div.bc-lane", {}, [
          el("div.bc-lane__top", {}, [
            el("div", {}, [el("strong", {}, [`+${lane.number}`]), lane.label && lane.label !== lane.number ? el("small", {}, [` ${lane.label}`]) : null]),
            el("span.bc-badge", { class: `is-${lane.status}` }, [statusWord(lane.status)]),
          ]),
          laneBar.node,
          el("div.bc-lane__meta", {}, [
            `${laneBar.pct}% · Sent ${lane.sent || 0} · Failed ${lane.failed || 0}${lane.retrying ? ` · Retrying ${lane.retrying}` : ""}${lane.pending ? ` · Pending ${lane.pending}` : ""}${lane.skipped ? ` · Skipped ${lane.skipped}` : ""} · ${lane.total || 0} rows`,
          ]),
          lane.error_detail ? el("div.bc-lane__err", {}, [lane.error_detail]) : null,
        ])
      );
    }
    if ((b.warnings || []).length) {
      batchDetail.append(
        el("details.bc-details", {}, [
          el("summary", {}, [`Rows skipped while reading the sheet (${b.warnings.length})`]),
          el("ul.bc-warnings", {}, b.warnings.map((w) => el("li", {}, [w]))),
        ])
      );
    }
  }

  function pollBatch(id) {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      try {
        const full = await bulkCampaigns.get(id);
        if (state.tab === "batches" && state.activeBatchId === id) renderBatchDetail(full);
        if (!isLive(full)) {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          const c = full.counts || {};
          toast(`Excel campaign ${statusWord(full.status).toLowerCase()}: ${c.sent || 0} sent, ${c.failed || 0} failed.`, c.failed ? "err" : "ok");
          loadBatches({ quiet: true });
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
  }

  /* ---- boot ------------------------------------------------------------- */

  renderMapping();
  renderSummary();
  renderPhonePreview();
  refreshStartState();
  loadNumbers();
  loadTemplates();
  return dialog;
}

/* -------------------------------------------------------------- menu item */

/**
 * "Excel campaigns" right under "Campaign" in the hamburger menu. Injected
 * here, so inbox.js — worked on by other sessions — does not change; the
 * menu is built once when the inbox mounts, which may be after this module
 * has loaded, hence the observer.
 */
function injectMenuItem() {
  const menu = document.querySelector(".sidebar__menu");
  if (!menu) return false;
  if (menu.querySelector(".bc-menu-item")) return true;
  const item = el("button.btn.menu__item.bc-menu-item", { type: "button", onclick: () => openBulkCampaignModal() }, [
    icon("file", { size: 16 }),
    "Excel campaigns",
  ]);
  const after = [...menu.querySelectorAll(".menu__item")].find((b) => b.textContent.trim() === "Campaign");
  if (after) after.after(item);
  else menu.append(item);
  return true;
}

if (!injectMenuItem()) {
  const observer = new MutationObserver(() => {
    if (injectMenuItem()) observer.disconnect();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
}
