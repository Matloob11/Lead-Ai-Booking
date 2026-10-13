/**
 * Campaigns — bulk approved-template send.
 *
 * Recipients come from the fixed Excel layout: {{1}}, Number, {{2}}…{{n}}.
 * Each row fills that recipient's template placeholders. Owner Data is matched
 * or created on New Availability (SPA 1042 / category 14) as sends go out.
 */

import { campaigns, catalog, inbox } from "../api/api.js";
import { clear, debounce, el, formatBytes, modal, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";

const PLACEHOLDER = /\{\{(\d+)\}\}/g;
const MAX_VISIBLE_BUTTONS = 3;
const MEDIA_HEADERS = { IMAGE: "image", VIDEO: "video", DOCUMENT: "document" };
const ACCEPT = {
  IMAGE: "image/jpeg,image/png",
  VIDEO: "video/mp4,video/3gpp",
  DOCUMENT: ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt",
};

function placeholdersIn(text) {
  const found = new Set();
  String(text || "").replace(PLACEHOLDER, (_, n) => found.add(n));
  return [...found].sort((a, b) => Number(a) - Number(b));
}

function sampleFor(text, n) {
  const source = String(text || "");
  const at = source.indexOf(`{{${n}}}`);
  if (at === -1) return `Value for {{${n}}}`;
  const before = source.slice(Math.max(0, at - 24), at).trimStart();
  const after = source.slice(at + `{{${n}}}`.length, at + `{{${n}}}`.length + 16).trimEnd();
  return `…${before}▮${after}…`.replace(/\s+/g, " ");
}

function withValues(text, values) {
  const frag = document.createDocumentFragment();
  const source = String(text || "");
  let cursor = 0;
  PLACEHOLDER.lastIndex = 0;
  for (let match; (match = PLACEHOLDER.exec(source)); ) {
    if (match.index > cursor) frag.append(document.createTextNode(source.slice(cursor, match.index)));
    const value = (values[match[1]] || "").trim();
    frag.append(value ? document.createTextNode(value) : el("span.camp-hole", {}, [match[0]]));
    cursor = match.index + match[0].length;
  }
  if (cursor < source.length) frag.append(document.createTextNode(source.slice(cursor)));
  return frag;
}

function svg(paths, { size = 15 } = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("viewBox", "0 0 24 24");
  node.setAttribute("width", size);
  node.setAttribute("height", size);
  node.setAttribute("fill", "none");
  node.setAttribute("stroke", "currentColor");
  node.setAttribute("stroke-width", "2");
  node.setAttribute("stroke-linecap", "round");
  node.setAttribute("stroke-linejoin", "round");
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    node.appendChild(path);
  }
  return node;
}

const BUTTON_ICON = {
  URL: () =>
    svg([
      "M10 13a5 5 0 007.5.5l3-3a5 5 0 00-7-7l-1.7 1.7",
      "M14 11a5 5 0 00-7.5-.5l-3 3a5 5 0 007 7l1.7-1.7",
    ]),
  PHONE_NUMBER: () =>
    svg([
      "M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012 4.2 2 2 0 014 2h3a2 2 0 012 1.7c.1.9.3 1.8.6 2.7a2 2 0 01-.4 2.1L8 9.8a16 16 0 006 6l1.3-1.2a2 2 0 012.1-.5c.9.3 1.8.5 2.7.6A2 2 0 0122 16.9z",
    ]),
  COPY_CODE: () => svg(["M9 9h10v10H9z", "M5 15V5h10"]),
  QUICK_REPLY: () => svg(["M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"]),
};

function buttonIcon(type) {
  return (BUTTON_ICON[type] || BUTTON_ICON.QUICK_REPLY)();
}

function fieldLabel(label, control, hint) {
  return el("label.camp-field", {}, [
    el("span.camp-field__label", {}, [label]),
    control,
    hint ? el("span.camp-field__hint", {}, [hint]) : null,
  ]);
}

export function openCampaignModal() {
  const numberSelect = el("select.camp-line__native", { hidden: true, tabindex: "-1" });
  const numberValue = el("span.camp-line__value.is-placeholder", {}, ["WhatsApp number"]);
  const numberSearch = el("input.camp-line__input", {
    type: "search",
    placeholder: "Search name or number",
    autocomplete: "off",
    hidden: true,
    "aria-label": "Search WhatsApp numbers",
  });
  const numberList = el("ul.camp-line__list", { hidden: true, role: "listbox" });
  const numberBox = el("div.camp-line__box", {
    tabindex: "0",
    role: "combobox",
    "aria-expanded": "false",
    "aria-haspopup": "listbox",
  }, [numberValue, numberSearch]);
  const numberPicker = el("div.camp-line", {}, [numberBox, numberList, numberSelect]);
  const templateSelect = el("select.field", { disabled: true });
  const templateField = fieldLabel("Approved template", templateSelect);
  templateField.hidden = true;
  const nameInput = el("input.field", {
    type: "text",
    placeholder: "e.g. March owner follow-up",
    autocomplete: "off",
  });
  const phonesArea = el("textarea.field.camp-phones", {
    rows: 7,
    placeholder: "One number per line\n971501234567\n0501234567, Name\nOptional: Name, 9715…",
  });
  const csvInput = el("input", {
    type: "file",
    accept: ".xlsx,.xlsm,.csv,text/csv",
    hidden: true,
  });
  const csvName = el("span.camp-csv__name", {}, ["No file chosen"]);
  const fieldsBox = el("div.camp-fields");
  const recipientsBox = el("div.camp-recipients", {}, [
    el("div.camp-recipients__empty", {}, ["Paste numbers or upload a CSV to preview the list."]),
  ]);
  const bubble = el("div.camp-bubble.is-empty");
  const bubbleButtons = el("div.camp-btns");
  const statusBox = el("div.camp-status");
  const errorBox = el("div.camp-error", { hidden: true });
  const sendBtn = el("button.btn.btn--primary", { type: "button", disabled: true }, [
    "Start campaign",
  ]);

  const historyList = el("div.camp-hist__list");
  const historyDetail = el("div.camp-hist__detail");
  const historyChats = el("div.camp-hist__chats");
  const historyEmpty = () => {
    clear(historyDetail).append(
      el("div.camp-hist__empty", {}, [
        el("div.camp-hist__empty-title", {}, ["Select a campaign"]),
        el("p", {}, [
          "Choose a row on the left to see sent / failed counts, retry status, and open chats.",
        ]),
      ])
    );
    clear(historyChats).append(
      el("div.camp-hist__empty", {}, [
        el("div.camp-hist__empty-title", {}, ["Chats"]),
        el("p", {}, ["Recipient chats show here once a campaign is selected."]),
      ])
    );
  };
  historyEmpty();

  const state = {
    numbers: [],
    templates: [],
    csvFile: null,
    body: {},
    headerText: {},
    buttonVars: {},
    headerMedia: null,
    uploading: false,
    recipientCount: 0,
    previewSample: [],
    pollTimer: null,
    histPollTimer: null,
    tab: "new",
    activeCampaignId: null,
  };

  const phonePreview = el("div.camp-phone", {}, [
    el("div.camp-phone__bar", {}, [
      el("div.camp-phone__avatar"),
      el("div.camp-phone__who", {}, [
        el("div.camp-phone__name", {}, ["Campaign preview"]),
        el("div.camp-phone__sub", {}, ["First Excel row · live fill"]),
      ]),
    ]),
    el("div.camp-phone__screen", {}, [
      el("div.camp-out", {}, [bubble, bubbleButtons]),
    ]),
  ]);

  const left = el("div.camp-left", {}, [
    el("div.camp-intro", {}, [
      el("div.camp-intro__kicker", {}, ["Official API"]),
      el("p.camp-intro__text", {}, [
        "Send one approved template to many owners. Each send opens the chat and creates Owner Data when needed.",
      ]),
    ]),
    el("section.camp-card", {}, [
      el("header.camp-card__head", {}, [
        el("span.camp-step", {}, ["1"]),
        el("div", {}, [
          el("h3.camp-card__title", {}, ["Number & template"]),
        ]),
      ]),
      numberPicker,
      templateField,
      fieldLabel("Campaign name", nameInput),
    ]),
    el("section.camp-card", {}, [
      el("header.camp-card__head", {}, [
        el("span.camp-step", {}, ["2"]),
        el("div", {}, [
          el("h3.camp-card__title", {}, ["Template fields"]),
          el("p.camp-card__sub", {}, [
            "Body values come from Excel. Header media or URL suffixes are set once here.",
          ]),
        ]),
      ]),
      fieldsBox,
    ]),
    el("section.camp-card", {}, [
      el("header.camp-card__head", {}, [
        el("span.camp-step", {}, ["3"]),
        el("div", {}, [
          el("h3.camp-card__title", {}, ["Recipients"]),
          el("p.camp-card__sub", {}, ["Upload the fixed Excel sheet. Column order does not matter."]),
        ]),
      ]),
      el("div.camp-format", {}, [
        el("span.camp-format__label", {}, ["Required columns"]),
        el("div.camp-format__chips", {}, [
          el("code.camp-chip", {}, ["{{1}}"]),
          el("code.camp-chip.camp-chip--key", {}, ["Number"]),
          el("code.camp-chip", {}, ["{{2}}"]),
          el("code.camp-chip", {}, ["{{3}}"]),
          el("code.camp-chip", {}, ["{{n}}"]),
        ]),
        el("p.camp-format__hint", {}, [
          "Number = phone · {{1}} = Owner Data name · other {{n}} fill the template.",
        ]),
      ]),
      el("div.camp-csv", {}, [
        el("button.btn.btn--primary.btn--sm", {
          type: "button",
          onclick: () => csvInput.click(),
        }, [icon("folder", { size: 14 }), " Upload Excel"]),
        csvName,
        el("button.btn.btn--ghost.btn--sm.camp-csv__clear", {
          type: "button",
          hidden: true,
          onclick: () => {
            state.csvFile = null;
            csvInput.value = "";
            csvName.textContent = "No file chosen";
            csvName.nextElementSibling.hidden = true;
            refreshRecipients();
            refreshSendState();
          },
        }, ["Clear"]),
        csvInput,
      ]),
      el("details.camp-paste", {}, [
        el("summary", {}, ["Paste numbers instead (templates with no body variables)"]),
        fieldLabel("", phonesArea, "UAE 05… converts to 971… · max 500"),
      ]),
      recipientsBox,
    ]),
    errorBox,
    statusBox,
  ]);

  const right = el("div.camp-right", {}, [
    el("div.camp-right__head", {}, [
      el("div.camp-right__title", {}, ["Live preview"]),
      el("p.camp-right__hint", {}, [
        "Shows the first Excel row. Fixed buttons cannot be edited here.",
      ]),
    ]),
    phonePreview,
  ]);

  const actionsBar = el("div.camp-actions", {}, [
    el("p.camp-actions__hint", {}, [
      "Campaigns keep running on the server if you close this or switch tabs — open History to watch progress.",
    ]),
    el("div.camp-actions__btns", {}, [
      el("button.btn.btn--ghost", {
        type: "button",
        onclick: () => setTab("history"),
      }, ["History"]),
      sendBtn,
    ]),
  ]);

  const newPane = el("div.camp.camp-pane.is-active", { "data-pane": "new" }, [
    el("div.camp-main", {}, [left, right]),
    actionsBar,
  ]);
  const historyPane = el("div.camp-hist.camp-pane", { "data-pane": "history", hidden: true }, [
    el("aside.camp-hist__list-wrap", {}, [
      el("div.camp-hist__head", {}, [
        el("h3.camp-hist__heading", {}, ["Past campaigns"]),
        el("p.camp-hist__blurb", {}, ["Failed numbers retry every 5 min · max 5 tries"]),
      ]),
      historyList,
    ]),
    historyDetail,
    historyChats,
  ]);

  const tabNew = el(
    "button.camp-tab.is-active",
    { type: "button", role: "tab", "aria-selected": "true" },
    ["New campaign"]
  );
  const tabHist = el(
    "button.camp-tab",
    { type: "button", role: "tab", "aria-selected": "false" },
    ["History"]
  );
  const tabs = el("div.camp-tabs", { role: "tablist" }, [tabNew, tabHist]);
  const titleEl = el("span", {}, ["New campaign"]);

  const body = el("div.camp-shell", {}, [tabs, newPane, historyPane]);

  document.addEventListener("keydown", onNumberKey, true);
  document.addEventListener("pointerdown", onNumberPointer, true);

  const dialog = modal(titleEl, body, {
    wide: true,
    onClose: () => {
      document.removeEventListener("keydown", onNumberKey, true);
      document.removeEventListener("pointerdown", onNumberPointer, true);
      if (state.pollTimer) clearInterval(state.pollTimer);
      if (state.histPollTimer) clearInterval(state.histPollTimer);
      if (state.headerMedia?.previewUrl) URL.revokeObjectURL(state.headerMedia.previewUrl);
    },
  });
  dialog.box.classList.add("modal__box--campaign");

  function setTab(which) {
    state.tab = which;
    const isNew = which === "new";
    tabNew.classList.toggle("is-active", isNew);
    tabHist.classList.toggle("is-active", !isNew);
    tabNew.setAttribute("aria-selected", isNew ? "true" : "false");
    tabHist.setAttribute("aria-selected", isNew ? "false" : "true");
    newPane.hidden = !isNew;
    historyPane.hidden = isNew;
    newPane.classList.toggle("is-active", isNew);
    historyPane.classList.toggle("is-active", !isNew);
    titleEl.textContent = isNew ? "New campaign" : "Campaign history";
    if (!isNew) {
      loadHistory();
      startHistoryListPoll();
    } else if (state.histPollTimer) {
      clearInterval(state.histPollTimer);
      state.histPollTimer = null;
    }
  }
  tabNew.addEventListener("click", () => setTab("new"));
  tabHist.addEventListener("click", () => setTab("history"));

  function selectedTemplate() {
    return state.templates.find((t) => String(t.id) === String(templateSelect.value)) || null;
  }

  function textField(label, hint, key, bucket, onChange) {
    const input = el("input.field", {
      type: "text",
      placeholder: hint,
      autocomplete: "off",
      value: bucket[key] || "",
      oninput: (event) => {
        bucket[key] = event.target.value;
        onChange?.();
      },
    });
    return fieldLabel(label, input);
  }

  function mediaField(format) {
    const kind = MEDIA_HEADERS[format] || "file";
    const status = el("div.camp-media__status", {}, [
      state.headerMedia
        ? `${state.headerMedia.name} · ${formatBytes(state.headerMedia.size)}`
        : `This template needs a ${kind} header — one file for the whole campaign.`,
    ]);
    const picker = el("input", { type: "file", accept: ACCEPT[format] || "", hidden: true });
    const pick = el("button.btn.btn--ghost.btn--sm", {
      type: "button",
      onclick: () => picker.click(),
    }, [`Choose ${kind}`]);

    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      picker.value = "";
      if (!file) return;
      if (!numberSelect.value) {
        toast("Pick a WhatsApp number first", "err");
        return;
      }
      state.uploading = true;
      if (state.headerMedia?.previewUrl) URL.revokeObjectURL(state.headerMedia.previewUrl);
      state.headerMedia = null;
      status.textContent = `Uploading ${file.name}…`;
      refreshSendState();
      renderMessagePreview();

      try {
        const result = await inbox.uploadMedia(file, { numberId: numberSelect.value }).promise;
        state.headerMedia = {
          media_id: result.media_id,
          name: file.name,
          size: file.size,
          previewUrl: format === "IMAGE" ? URL.createObjectURL(file) : "",
        };
        status.textContent = `${file.name} · ${formatBytes(file.size)}`;
      } catch (err) {
        status.textContent = `Upload failed: ${err.message}`;
        toast(err.message || "Upload failed", "err");
      } finally {
        state.uploading = false;
        refreshSendState();
        renderMessagePreview();
      }
    });

    return el("div.camp-media", {}, [
      el("span.camp-field__label", {}, [`${kind[0].toUpperCase()}${kind.slice(1)} header`]),
      el("div.camp-media__row", {}, [pick, status]),
      picker,
    ]);
  }

  function renderFields() {
    clear(fieldsBox);
    const template = selectedTemplate();
    state.body = {};
    state.headerText = {};
    state.buttonVars = {};
    if (state.headerMedia?.previewUrl) URL.revokeObjectURL(state.headerMedia.previewUrl);
    state.headerMedia = null;
    state.uploading = false;

    if (!template) {
      fieldsBox.append(
        el("div.camp-empty", {}, ["Choose a number and an approved template to see the fields it needs."])
      );
      renderMessagePreview();
      refreshSendState();
      return;
    }

    const header = template.header;
    let added = 0;

    if (template.requires_header_media) {
      fieldsBox.append(mediaField(header.format));
      added += 1;
    } else if (header?.format === "TEXT") {
      for (const n of placeholdersIn(header.text)) {
        fieldsBox.append(
          textField(`Header {{${n}}}`, "Text for the header", n, state.headerText, () => {
            renderMessagePreview();
            refreshSendState();
          })
        );
        added += 1;
      }
    }

    for (const n of placeholdersIn(template.body_text)) {
      if (template.variable_count > 0) continue;
      fieldsBox.append(
        textField(`Body {{${n}}}`, sampleFor(template.body_text, n), n, state.body, () => {
          renderMessagePreview();
          refreshSendState();
        })
      );
      added += 1;
    }

    if (template.variable_count > 0) {
      fieldsBox.append(
        el("div.camp-excel-note", {}, [
          `This template needs ${template.variable_count} body placeholder${template.variable_count > 1 ? "s" : ""}. Upload the Excel file — values come from columns {{1}} through {{${template.variable_count}}}.`,
        ])
      );
      added += 1;
    }

    for (const button of template.buttons || []) {
      if (!button.variable_count) continue;
      fieldsBox.append(
        textField(
          `Link for “${button.text || "Button"}”`,
          "Value appended to the approved URL (the {{1}} at the end)",
          String(button.index),
          state.buttonVars,
          () => {
            renderMessagePreview();
            refreshSendState();
          }
        )
      );
      added += 1;
    }

    if ((template.buttons || []).length) {
      const fixed = (template.buttons || []).filter((b) => !b.variable_count);
      fieldsBox.append(
        el("div.camp-buttons-note", {}, [
          el("div.camp-section__title", {}, ["Template buttons"]),
          el(
            "ul.camp-buttons-list",
            {},
            (template.buttons || []).map((b) =>
              el("li", {}, [
                buttonIcon(b.type),
                el("span", {}, [
                  b.text || "Button",
                  b.variable_count ? " — URL suffix required above" : " — fixed in template",
                ]),
              ])
            )
          ),
          fixed.length
            ? el("p.camp-field__hint", {}, [
                "Quick-reply / phone / fixed-link buttons are already approved — agents cannot rename them.",
              ])
            : null,
        ])
      );
    }

    if (!added) {
      fieldsBox.append(
        el("div.camp-empty", {}, ["This template has nothing to fill in — it sends as written."])
      );
    }

    renderMessagePreview();
    refreshSendState();
  }

  function renderMessagePreview() {
    const template = selectedTemplate();
    clear(bubble);
    clear(bubbleButtons);

    if (!template) {
      bubble.classList.add("is-empty");
      bubble.append(el("div.camp-bubble__hint", {}, ["Your template will appear here."]));
      return;
    }
    bubble.classList.remove("is-empty");

    const header = template.header;
    if (template.requires_header_media) {
      if (header?.format === "IMAGE" && state.headerMedia?.previewUrl) {
        bubble.append(el("img.camp-bubble__image", { src: state.headerMedia.previewUrl, alt: "" }));
      } else {
        const label = state.headerMedia
          ? `${state.headerMedia.name} · ${formatBytes(state.headerMedia.size)}`
          : state.uploading
            ? "Uploading…"
            : `${MEDIA_HEADERS[header?.format] || "media"} header — not chosen yet`;
        bubble.append(
          el("div.camp-bubble__media", { class: state.headerMedia ? "" : "is-missing" }, [label])
        );
      }
    } else if (header?.format === "TEXT" && header.text) {
      bubble.append(el("div.camp-bubble__header", {}, [withValues(header.text, state.headerText)]));
    }

    bubble.append(
      el("div.camp-bubble__body", {}, [
        withValues(
          template.body_text,
          state.previewSample[0]?.variables || state.body
        ),
      ])
    );
    if (template.footer_text) {
      bubble.append(el("div.camp-bubble__footer", {}, [template.footer_text]));
    }
    bubble.append(
      el("div.camp-bubble__meta", {}, [
        new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      ])
    );

    const buttons = template.buttons || [];
    for (const button of buttons.slice(0, MAX_VISIBLE_BUTTONS)) {
      bubbleButtons.append(
        el("div.camp-btn", {}, [buttonIcon(button.type), el("span", {}, [button.text || "Button"])])
      );
    }
    if (buttons.length > MAX_VISIBLE_BUTTONS) {
      bubbleButtons.append(
        el("div.camp-btn.camp-btn--more", {}, [
          buttonIcon("QUICK_REPLY"),
          el("span", {}, ["See all options"]),
        ])
      );
    }
  }

  function missing() {
    if (!numberSelect.value) return "Pick a WhatsApp number.";
    const template = selectedTemplate();
    if (!template) return "Pick an approved template.";
    if (state.uploading) return "Wait for the header upload to finish.";
    if (template.requires_header_media && !state.headerMedia?.media_id) {
      return `Choose the ${MEDIA_HEADERS[template.header.format]} for the header.`;
    }
    const header = template.header;
    if (
      header?.format === "TEXT" &&
      placeholdersIn(header.text).some((n) => !(state.headerText[n] || "").trim())
    ) {
      return "Fill in every header field.";
    }
    const needsExcel = (template.variable_count || 0) > 0;
    if (needsExcel) {
      if (!state.csvFile) {
        return "Upload the Excel file with {{1}}, Number, and every {{n}} column this template needs.";
      }
    } else if (placeholdersIn(template.body_text).some((n) => !(state.body[n] || "").trim())) {
      return "Fill in every body field.";
    }
    const button = (template.buttons || []).find(
      (b) => b.variable_count && !(state.buttonVars[String(b.index)] || "").trim()
    );
    if (button) return `Fill in the link for “${button.text}”.`;
    if (!needsExcel && !phonesArea.value.trim() && !state.csvFile) {
      return "Paste numbers or upload a spreadsheet.";
    }
    if (state.recipientCount < 1) return "No valid recipients found yet — check the Excel format.";
    return "";
  }

  function refreshSendState() {
    const blocked = missing();
    sendBtn.disabled = Boolean(blocked);
    errorBox.hidden = true;
  }

  function numberOptionLabel(n) {
    const phone = String(n.phone_number || "").trim();
    const name = String(n.title || n.label || "").trim();
    if (phone && name && name !== phone) return `${phone} · ${name}`;
    return name || phone || `#${n.id}`;
  }

  function numberMatchesQuery(n, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return true;
    const phone = String(n.phone_number || "");
    const name = String(n.title || n.label || "").toLowerCase();
    const digits = q.replace(/\D/g, "");
    if (name.includes(q)) return true;
    if (phone.toLowerCase().includes(q)) return true;
    if (digits && phone.replace(/\D/g, "").includes(digits)) return true;
    return false;
  }

  function syncHiddenNumbers() {
    const selected = numberSelect.value;
    clear(numberSelect);
    numberSelect.append(el("option", { value: "" }, [""]));
    for (const n of state.numbers) {
      numberSelect.append(el("option", { value: String(n.id) }, [numberOptionLabel(n)]));
    }
    if ([...numberSelect.options].some((opt) => opt.value === selected && selected)) {
      numberSelect.value = selected;
    }
    paintNumberFace();
  }

  function paintNumberFace() {
    const chosen = state.numbers.find((n) => String(n.id) === String(numberSelect.value));
    numberValue.textContent = chosen ? numberOptionLabel(chosen) : "WhatsApp number";
    numberValue.classList.toggle("is-placeholder", !chosen);
  }

  function renderNumberList() {
    clear(numberList);
    const query = numberSearch.value;
    let shown = 0;
    for (const n of state.numbers) {
      if (!numberMatchesQuery(n, query)) continue;
      shown += 1;
      const on = String(n.id) === String(numberSelect.value);
      numberList.append(
        el("li", {}, [
          el(`button.camp-line__opt${on ? ".is-on" : ""}`, {
            type: "button",
            role: "option",
            "aria-selected": on ? "true" : "false",
            onclick: (event) => {
              event.stopPropagation();
              chooseNumber(n.id);
            },
          }, [numberOptionLabel(n)]),
        ])
      );
    }
    if (!shown) {
      numberList.append(
        el("li.camp-line__empty", {}, [query.trim() ? "No numbers match" : "No numbers"])
      );
    }
  }

  function openNumberList() {
    state.numberOpen = true;
    numberSearch.hidden = false;
    numberValue.hidden = true;
    numberList.hidden = false;
    numberBox.classList.add("is-open");
    numberBox.setAttribute("aria-expanded", "true");
    numberSearch.value = "";
    renderNumberList();
    numberSearch.focus();
  }

  function closeNumberList() {
    if (!state.numberOpen) return;
    state.numberOpen = false;
    numberSearch.hidden = true;
    numberValue.hidden = false;
    numberList.hidden = true;
    numberBox.classList.remove("is-open");
    numberBox.setAttribute("aria-expanded", "false");
    paintNumberFace();
  }

  function chooseNumber(id) {
    numberSelect.value = String(id);
    closeNumberList();
    loadTemplates();
    refreshSendState();
  }

  function onNumberKey(event) {
    if (!state.numberOpen || event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    closeNumberList();
  }

  function onNumberPointer(event) {
    if (!state.numberOpen) return;
    if (numberPicker.contains(event.target)) return;
    closeNumberList();
  }

  async function loadNumbers() {
    try {
      const data = await catalog.numbers();
      state.numbers = Array.isArray(data) ? data : data.numbers || [];
    } catch (err) {
      toast(err?.message || "Could not load numbers", "err");
      state.numbers = [];
    }
    syncHiddenNumbers();
    if (state.numberOpen) renderNumberList();
  }

  async function loadTemplates() {
    const id = numberSelect.value;
    clear(templateSelect);
    templateSelect.disabled = true;
    state.templates = [];
    renderFields();
    templateField.hidden = !id;
    if (!id) {
      templateSelect.append(el("option", { value: "" }, ["Select approved template…"]));
      return;
    }
    templateSelect.append(el("option", { value: "" }, ["Loading…"]));
    try {
      const data = await catalog.templates(id);
      state.templates = Array.isArray(data) ? data : data.templates || [];
    } catch (err) {
      toast(err?.message || "Could not load templates", "err");
      state.templates = [];
    }
    clear(templateSelect);
    templateSelect.append(el("option", { value: "" }, ["Select approved template…"]));
    let count = 0;
    for (const t of state.templates) {
      if (String(t.status || "").toUpperCase() !== "APPROVED") continue;
      const bits = [t.name, t.language || "en"];
      if (t.variable_count) bits.push(`${t.variable_count} var${t.variable_count > 1 ? "s" : ""}`);
      if (t.requires_header_media) bits.push("media");
      if ((t.buttons || []).length) bits.push(`${t.buttons.length} btn`);
      templateSelect.append(el("option", { value: String(t.id) }, [bits.join(" · ")]));
      count += 1;
    }
    if (!count) {
      templateSelect.append(el("option", { value: "", disabled: true }, ["No approved templates on this number"]));
    }
    templateSelect.disabled = false;
    refreshSendState();
  }

  async function refreshRecipients() {
    const template = selectedTemplate();
    const text = phonesArea.value;
    if (!text.trim() && !state.csvFile) {
      state.recipientCount = 0;
      state.previewSample = [];
      clear(recipientsBox).append(
        el("div.camp-recipients__empty", {}, [
          template?.variable_count
            ? "Upload the Excel file to preview recipients."
            : "Paste numbers or upload a spreadsheet to preview the list.",
        ])
      );
      renderMessagePreview();
      refreshSendState();
      return;
    }
    if (template?.variable_count && !state.csvFile) {
      state.recipientCount = 0;
      state.previewSample = [];
      clear(recipientsBox).append(
        el("div.camp-recipients__empty", {}, ["Upload the Excel file — this template needs per-row values."])
      );
      refreshSendState();
      return;
    }
    clear(recipientsBox).append(el("div.camp-recipients__empty", {}, ["Parsing…"]));
    try {
      const data = await campaigns.preview({
        recipients_text: text,
        csv: state.csvFile,
        template_id: template?.id,
      });
      state.recipientCount = data.count || 0;
      state.previewSample = data.sample || [];
      const warnings = data.warnings || [];
      const sample = state.previewSample;
      clear(recipientsBox);
      recipientsBox.append(
        el("div.camp-recipients__head", {}, [
          el("strong", {}, [
            `${state.recipientCount} recipient${state.recipientCount === 1 ? "" : "s"}`,
          ]),
          state.recipientCount > sample.length
            ? el("span", {}, [` · showing first ${sample.length}`])
            : null,
        ])
      );
      if (warnings.length) {
        recipientsBox.append(
          el("div.camp-recipients__warn", {}, [
            el("strong", {}, ["Some rows were skipped: "]),
            warnings.slice(0, 5).join(" "),
          ])
        );
      }
      if (sample.length) {
        recipientsBox.append(
          el(
            "ul.camp-sample",
            {},
            sample.map((r) => {
              const vars = r.variables
                ? Object.entries(r.variables)
                    .sort(([a], [b]) => Number(a) - Number(b))
                    .map(([k, v]) => `{{${k}}}: ${v}`)
                    .join(" · ")
                : "";
              return el("li", {}, [
                `+${r.phone}${r.name ? ` · ${r.name}` : ""}`,
                vars ? el("span.camp-sample__vars", {}, [vars]) : null,
              ]);
            })
          )
        );
      } else {
        recipientsBox.append(
          el("div.camp-recipients__empty", {}, ["Wrong format or no valid rows found."])
        );
      }
      renderMessagePreview();
    } catch (err) {
      state.recipientCount = 0;
      state.previewSample = [];
      clear(recipientsBox).append(
        el("div.camp-recipients__empty.camp-recipients__bad", {}, [
          err?.message || "Wrong format — check the Excel headers.",
        ])
      );
    }
    refreshSendState();
  }

  function countsLine(camp) {
    const parts = [
      `Sent ${camp.sent || 0}`,
      `Failed ${camp.failed || 0}`,
      camp.retrying ? `Retrying ${camp.retrying}` : null,
      camp.pending ? `Pending ${camp.pending}` : null,
      camp.skipped ? `Skipped ${camp.skipped}` : null,
      `Total ${camp.total || 0}`,
    ].filter(Boolean);
    return parts.join(" · ");
  }

  function statsRow(camp) {
    return el("div.camp-stats", {}, [
      el("div.camp-stat.is-sent", {}, [
        el("span.camp-stat__n", {}, [String(camp.sent || 0)]),
        el("span.camp-stat__l", {}, ["Sent"]),
      ]),
      el("div.camp-stat.is-failed", {}, [
        el("span.camp-stat__n", {}, [String(camp.failed || 0)]),
        el("span.camp-stat__l", {}, ["Failed"]),
      ]),
      el("div.camp-stat.is-retry", {}, [
        el("span.camp-stat__n", {}, [String(camp.retrying || 0)]),
        el("span.camp-stat__l", {}, ["Retrying"]),
      ]),
      el("div.camp-stat", {}, [
        el("span.camp-stat__n", {}, [String(camp.total || 0)]),
        el("span.camp-stat__l", {}, ["Total"]),
      ]),
    ]);
  }

  function recipientLabel(r) {
    const tries = `${r.attempt_count || 0}/${r.max_attempts || 5}`;
    if (r.status === "sent") return `Sent (try ${tries})`;
    if (r.status === "exhausted") return `Failed permanently (try ${tries})`;
    if (r.status === "failed") return `Retrying (try ${tries})`;
    if (r.status === "pending") return `Pending (try ${tries})`;
    return r.status;
  }

  /** Group permanent/failed rows so History highlights real issues (cap vs undeliverable). */
  function failureBreakdown(recipients) {
    const fails = (recipients || []).filter(
      (r) => r.status === "failed" || r.status === "exhausted" || r.status === "skipped"
    );
    let marketingCap = 0;
    let undeliverable = 0;
    let experiment = 0;
    let paused = 0;
    let other = 0;
    for (const r of fails) {
      const d = String(r.error_detail || "");
      if (/Skipped:.*marketing daily cap/i.test(d)) paused += 1;
      else if (/131049|marketing daily cap/i.test(d)) marketingCap += 1;
      else if (/undeliverable|131026/i.test(d)) undeliverable += 1;
      else if (/130472|experiment/i.test(d)) experiment += 1;
      else other += 1;
    }
    return { fails, marketingCap, undeliverable, experiment, paused, other };
  }

  function failureHighlights(camp) {
    const { fails, marketingCap, undeliverable, experiment, paused, other } =
      failureBreakdown(camp.recipients);
    if (!fails.length) return null;
    const chips = [];
    const push = (count, label, kind) => {
      if (!count) return;
      chips.push(
        el(`div.camp-issue.is-${kind}`, {}, [
          el("strong", {}, [String(count)]),
          el("span", {}, [label]),
        ])
      );
    };
    push(marketingCap, "Marketing daily cap", "cap");
    push(paused, "Paused after cap", "cap");
    push(undeliverable, "Not on WhatsApp", "undeliv");
    push(experiment, "Meta experiment block", "other");
    push(other, "Other errors", "other");
    return el("div.camp-issues", {}, chips);
  }

  function resendableCount(camp) {
    return (camp.recipients || []).filter((r) => {
      if (r.status === "skipped") return true;
      const d = String(r.error_detail || "");
      return r.status === "exhausted" && /131049|marketing daily cap/i.test(d);
    }).length;
  }

  function shortFailDetail(detail) {
    const d = String(detail || "");
    if (/131049|marketing daily cap/i.test(d)) return "Marketing cap";
    if (/undeliverable|131026/i.test(d)) return "Not on WhatsApp";
    if (/130472|experiment/i.test(d)) return "Experiment block";
    if (/Skipped:/i.test(d)) return "Skipped";
    const cut = d.replace(/\s+/g, " ").trim();
    return cut.length > 60 ? `${cut.slice(0, 57)}…` : cut;
  }

  async function startResend(camp, numberId, label) {
    const count = resendableCount(camp);
    const ok = window.confirm(
      `Send “${camp.template_name || "template"}” to ${count} number${count === 1 ? "" : "s"} ${label}?`
    );
    if (!ok) return null;
    try {
      const next = await campaigns.resendSkipped(camp.id, numberId);
      toast(`Campaign #${next.id} started · ${next.total} recipients`, "ok");
      state.activeCampaignId = next.id;
      setTab("history");
      showHistoryCampaign(next.id);
      pollCampaign(next.id);
      return next;
    } catch (e) {
      toast(e?.message || "Could not start campaign", "err");
      throw e;
    }
  }

  function openResendSkipped(camp) {
    const others = (state.numbers || []).filter(
      (n) => String(n.id) !== String(camp.number_id)
    );
    if (!others.length) {
      toast("No other WhatsApp number is assigned to you.", "err");
      return;
    }
    const count = resendableCount(camp);
    const filter = el("input.field", {
      type: "search",
      placeholder: "Search number…",
      autocomplete: "off",
    });
    const select = el("select.field");
    const fill = () => {
      const selected = select.value;
      clear(select);
      select.append(el("option", { value: "" }, ["Select number…"]));
      let shown = 0;
      for (const n of others) {
        if (!numberMatchesQuery(n, filter.value)) continue;
        select.append(el("option", { value: String(n.id) }, [numberOptionLabel(n)]));
        shown += 1;
      }
      if (filter.value.trim() && !shown) {
        select.append(
          el("option", { value: "", disabled: true }, ["No match"])
        );
      }
      if ([...select.options].some((opt) => opt.value === selected && selected)) {
        select.value = selected;
      }
    };
    fill();
    filter.addEventListener("input", fill);
    const err = el("div.camp-error", { hidden: true });
    const startBtn = el("button.btn.btn--primary", { type: "button" }, [
      `Send ${count}`,
    ]);
    const picker = modal(
      "Try another number",
      el("div.camp-resend-form", {}, [
        fieldLabel("WhatsApp number", el("div.camp-numpick", {}, [filter, select])),
        err,
        el("div.camp-actions__btns", {}, [startBtn]),
      ])
    );
    startBtn.addEventListener("click", async () => {
      if (!select.value) {
        err.hidden = false;
        err.textContent = "Pick a number.";
        return;
      }
      const chosen = others.find((n) => String(n.id) === String(select.value));
      startBtn.disabled = true;
      startBtn.textContent = "Starting…";
      err.hidden = true;
      try {
        await startResend(camp, select.value, `from +${chosen?.phone_number || "new number"}`);
        picker.close();
      } catch (e) {
        startBtn.disabled = false;
        startBtn.textContent = `Send ${count}`;
        err.hidden = false;
        err.textContent = e?.message || "Could not start";
      }
    });
  }

  function openRecipientChat(r) {
    if (!r.conversation_id) {
      toast("No chat yet for this number — send must succeed first (or wait for a retry).", "err");
      return;
    }
    if (typeof window.a7wa?.openConversation === "function") {
      window.a7wa.openConversation(r.conversation_id);
      toast("Opened chat in the inbox");
    } else {
      toast("Inbox is not ready to open chats yet.", "err");
    }
  }

  function renderChatsSide(camp) {
    clear(historyChats);
    historyChats.append(el("h3.camp-hist__chats-title", {}, ["Recipient chats"]));
    const rows = camp.recipients || [];
    if (!rows.length) {
      historyChats.append(
        el("div.camp-hist__empty", {}, [
          el("div.camp-hist__empty-title", {}, ["No recipients"]),
          el("p", {}, ["This campaign has no numbers yet."]),
        ])
      );
      return;
    }
    historyChats.append(
      el(
        "ul.camp-chat-list",
        {},
        rows.map((r) =>
          el("li.camp-chat-list__item", { class: `is-${r.status}` }, [
            el("div.camp-chat-list__meta", {}, [
              el("strong", {}, [r.name || `+${r.phone}`]),
              el("span", {}, [`+${r.phone}`]),
              el("span.camp-chat-list__status", {}, [recipientLabel(r)]),
              r.error_detail && r.status !== "sent"
                ? el("span.camp-chat-list__err", {}, [shortFailDetail(r.error_detail)])
                : null,
            ]),
            el("button.btn.btn--ghost.btn--sm", {
              type: "button",
              disabled: !r.conversation_id,
              onclick: () => openRecipientChat(r),
            }, [r.conversation_id ? "Open chat" : "No chat"]),
          ])
        )
      )
    );
  }

  function renderHistoryDetail(camp) {
    clear(historyDetail);
    const settled = (camp.sent || 0) + (camp.failed || 0) + (camp.skipped || 0);
    const pct = camp.total > 0 ? Math.round((settled / camp.total) * 100) : 0;
    const fill = el("div.camp-progress__fill");
    fill.style.width = `${Math.min(100, pct)}%`;
    historyDetail.append(
      el("div.camp-progress", {}, [
        el("div.camp-progress__top", {}, [
          el("strong", {}, [camp.name || `Campaign #${camp.id}`]),
          el("span.camp-progress__status", { class: `is-${camp.status}` }, [camp.status]),
        ]),
        el("div.camp-progress__bar", {}, [fill]),
        el("div.camp-progress__meta", {}, [`${pct}% · ${countsLine(camp)}`]),
      ]),
      statsRow(camp)
    );
    const issues = failureHighlights(camp);
    if (issues) historyDetail.append(issues);
    const queuedAgain = resendableCount(camp);
    if (queuedAgain) {
      const sameBtn = el("button.btn.btn--primary.btn--sm", { type: "button" }, [
        `Retry same number (${queuedAgain})`,
      ]);
      const otherBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, [
        "Try another number",
      ]);
      sameBtn.addEventListener("click", async () => {
        sameBtn.disabled = true;
        otherBtn.disabled = true;
        sameBtn.textContent = "Starting…";
        try {
          await startResend(
            camp,
            camp.number_id,
            `from +${camp.number || "same number"}`
          );
        } catch (e) {
          sameBtn.disabled = false;
          otherBtn.disabled = false;
          sameBtn.textContent = `Retry same number (${queuedAgain})`;
        }
      });
      otherBtn.addEventListener("click", () => openResendSkipped(camp));
      historyDetail.append(
        el("div.camp-resend", {}, [
          el("div.camp-resend__btns", {}, [sameBtn, otherBtn]),
        ])
      );
    }

    const fails = (camp.recipients || []).filter(
      (r) => r.status === "failed" || r.status === "exhausted"
    );
    if (fails.length) {
      historyDetail.append(
        el("div.camp-fails", {}, [
          el("div.camp-section__title", {}, [`Failures (${fails.length})`]),
          el(
            "ul.camp-sample",
            {},
            fails.slice(0, 40).map((r) =>
              el("li", {}, [
                `+${r.phone}` +
                  (r.error_detail ? ` · ${shortFailDetail(r.error_detail)}` : ""),
              ])
            )
          ),
        ])
      );
    }
    renderChatsSide(camp);
  }

  function renderProgress(camp) {
    clear(statusBox);
    const doneBits = (camp.sent || 0) + (camp.failed || 0) + (camp.skipped || 0);
    const pct = camp.total > 0 ? Math.round((doneBits / camp.total) * 100) : 0;
    const fill = el("div.camp-progress__fill");
    fill.style.width = `${Math.min(100, pct)}%`;
    const live = el("div.camp-live", {}, [
      el("div.camp-live__title", {}, ["Running in the background"]),
      el("p.camp-live__hint", {}, [
        "You can close this modal or open History — sending continues on the server.",
      ]),
      el("div.camp-progress", {}, [
        el("div.camp-progress__top", {}, [
          el("strong", {}, [camp.name || `Campaign #${camp.id}`]),
          el("span.camp-progress__status", { class: `is-${camp.status}` }, [camp.status]),
        ]),
        el("div.camp-progress__bar", {}, [fill]),
        el("div.camp-progress__meta", {}, [countsLine(camp)]),
      ]),
    ]);

    const fails = (camp.recipients || [])
      .filter((r) => r.status === "failed" || r.status === "exhausted")
      .slice(0, 6);
    if (fails.length) {
      live.append(
        el("div.camp-fails", {}, [
          el("div.camp-section__title", {}, ["Recent failures"]),
          el(
            "ul.camp-sample",
            {},
            fails.map((r) =>
              el("li", {}, [
                `+${r.phone}` +
                  (r.error_detail ? ` · ${shortFailDetail(r.error_detail)}` : ""),
              ])
            )
          ),
        ])
      );
    }

    live.append(
      el("button.btn.btn--ghost.btn--sm", {
        type: "button",
        onclick: () => {
          state.activeCampaignId = camp.id;
          setTab("history");
          showHistoryCampaign(camp.id);
        },
      }, ["Open full history"])
    );
    statusBox.append(live);
  }

  async function showHistoryCampaign(id) {
    state.activeCampaignId = id;
    clear(historyDetail).append(
      el("div.camp-hist__empty", {}, [
        el("div.camp-hist__empty-title", {}, ["Loading…"]),
      ])
    );
    clear(historyChats).append(
      el("div.camp-hist__empty", {}, [
        el("div.camp-hist__empty-title", {}, ["Loading chats…"]),
      ])
    );
    try {
      const full = await campaigns.get(id);
      renderHistoryDetail(full);
      highlightHistoryRow(id);
    } catch (err) {
      clear(historyDetail).append(
        el("div.camp-hist__empty", {}, [
          el("div.camp-hist__empty-title", {}, ["Could not load"]),
          el("p", {}, [err?.message || "Try again."]),
        ])
      );
      clear(historyChats).append(
        el("div.camp-hist__empty", {}, [
          el("div.camp-hist__empty-title", {}, ["Chats"]),
          el("p", {}, ["Unavailable until the campaign loads."]),
        ])
      );
    }
  }

  function highlightHistoryRow(id) {
    for (const btn of historyList.querySelectorAll(".camp-hist__item")) {
      btn.classList.toggle("is-active", String(btn.dataset.id) === String(id));
    }
  }

  function isCampaignLive(c) {
    if (!c) return false;
    if (c.status === "running" || c.status === "queued" || c.status === "retrying") return true;
    return (c.retrying || 0) > 0 || (c.pending || 0) > 0;
  }

  function startHistoryListPoll() {
    if (state.histPollTimer) clearInterval(state.histPollTimer);
    state.histPollTimer = setInterval(() => {
      if (state.tab !== "history") return;
      refreshHistoryQuiet();
    }, 4000);
  }

  async function refreshHistoryQuiet() {
    try {
      const rows = await campaigns.list();
      const list = Array.isArray(rows) ? rows : [];
      const live = list.find(isCampaignLive);
      if (live && !state.pollTimer) pollCampaign(live.id);
      if (state.activeCampaignId) {
        const open = list.find((c) => String(c.id) === String(state.activeCampaignId));
        if (open) {
          // Refresh list chips without wiping the detail pane.
          for (const btn of historyList.querySelectorAll(".camp-hist__item")) {
            if (String(btn.dataset.id) !== String(open.id)) continue;
            const badge = btn.querySelector(".camp-hist__badge");
            if (badge) {
              badge.className = `camp-hist__badge is-${open.status}`;
              badge.textContent = open.status || "—";
            }
            const counts = btn.querySelector(".camp-hist__counts");
            if (counts) {
              clear(counts);
              counts.append(
                el("span.camp-hist__chip.is-sent", {}, [`Sent ${open.sent || 0}`]),
                el("span.camp-hist__chip.is-failed", {}, [`Failed ${open.failed || 0}`]),
                (open.retrying || 0) > 0
                  ? el("span.camp-hist__chip.is-retry", {}, [`Retry ${open.retrying}`])
                  : null,
                el("span.camp-hist__chip", {}, [`${open.total || 0} total`])
              );
            }
          }
        }
      }
      // Soft re-render list when statuses change a lot (new campaign appeared).
      const ids = list.map((c) => String(c.id)).join(",");
      if (state._histIds && state._histIds !== ids) {
        state._histIds = ids;
        loadHistory();
      } else {
        state._histIds = ids;
      }
    } catch {
      /* ignore */
    }
  }

  async function loadHistory() {
    clear(historyList).append(
      el("div.camp-hist__empty", {}, [
        el("div.camp-hist__empty-title", {}, ["Loading…"]),
      ])
    );
    try {
      const rows = await campaigns.list();
      const list = Array.isArray(rows) ? rows : [];
      state._histIds = list.map((c) => String(c.id)).join(",");
      clear(historyList);
      if (!list.length) {
        historyList.append(
          el("div.camp-hist__empty", {}, [
            el("div.camp-hist__empty-title", {}, ["No campaigns yet"]),
            el("p", {}, ["Start one from the New campaign tab."]),
          ])
        );
        historyEmpty();
        return;
      }
      for (const c of list) {
        const live = isCampaignLive(c);
        historyList.append(
          el("button.camp-hist__item", {
            type: "button",
            "data-id": String(c.id),
            class:
              (state.activeCampaignId === c.id ? "is-active " : "") +
              (live ? "is-live" : ""),
            onclick: () => {
              showHistoryCampaign(c.id);
              if (live) pollCampaign(c.id);
            },
          }, [
            el("div.camp-hist__item-top", {}, [
              el("strong", {}, [c.name || `#${c.id}`]),
              el(
                "span.camp-hist__badge",
                { class: `is-${c.status}` },
                [live ? `● ${c.status || "running"}` : c.status || "—"]
              ),
            ]),
            el("div.camp-hist__counts", {}, [
              el("span.camp-hist__chip.is-sent", {}, [`Sent ${c.sent || 0}`]),
              el("span.camp-hist__chip.is-failed", {}, [`Failed ${c.failed || 0}`]),
              (c.retrying || 0) > 0
                ? el("span.camp-hist__chip.is-retry", {}, [`Retry ${c.retrying}`])
                : null,
              el("span.camp-hist__chip", {}, [`${c.total || 0} total`]),
            ]),
            el("span.camp-hist__sub", {}, [
              [c.template_name, c.number].filter(Boolean).join(" · ") || "—",
            ]),
          ])
        );
      }
      const prefer =
        (state.activeCampaignId &&
          list.find((c) => String(c.id) === String(state.activeCampaignId))) ||
        list.find(isCampaignLive) ||
        list[0];
      if (prefer) {
        highlightHistoryRow(prefer.id);
        showHistoryCampaign(prefer.id);
        if (isCampaignLive(prefer)) pollCampaign(prefer.id);
      } else {
        historyEmpty();
      }
    } catch (err) {
      clear(historyList).append(
        el("div.camp-hist__empty", {}, [
          el("div.camp-hist__empty-title", {}, ["Could not load history"]),
          el("p", {}, [err?.message || "Try again."]),
        ])
      );
    }
  }

  async function pollCampaign(id) {
    state.activeCampaignId = id;
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      try {
        const camp = await campaigns.get(id);
        if (state.tab === "new") renderProgress(camp);
        if (state.tab === "history" && state.activeCampaignId === id) {
          renderHistoryDetail(camp);
        }
        // Keep polling while retries may still run.
        const settled =
          camp.status === "cancelled" ||
          (camp.status === "done" && !(camp.retrying || camp.pending));
        if (settled) {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          sendBtn.disabled = false;
          sendBtn.textContent = "Start another";
          toast(
            `Campaign finished: ${camp.sent || 0} sent, ${camp.failed || 0} failed` +
              (camp.retrying ? `, ${camp.retrying} still retrying` : ""),
            camp.failed ? "err" : "ok"
          );
          if (state.tab === "history") loadHistory();
        }
      } catch {
        /* keep polling */
      }
    }, 2500);
  }

  numberBox.addEventListener("click", () => {
    if (!state.numberOpen) openNumberList();
  });
  numberBox.addEventListener("keydown", (event) => {
    if (state.numberOpen) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openNumberList();
    }
  });
  numberSearch.addEventListener("input", () => renderNumberList());
  numberSearch.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    numberList.querySelector(".camp-line__opt")?.click();
  });
  templateSelect.addEventListener("change", () => {
    renderFields();
    refreshRecipients();
  });
  phonesArea.addEventListener("input", debounce(() => {
    refreshRecipients();
  }, 400));
  phonesArea.addEventListener("blur", () => refreshRecipients());
  csvInput.addEventListener("change", () => {
    state.csvFile = csvInput.files?.[0] || null;
    csvName.textContent = state.csvFile ? state.csvFile.name : "No file chosen";
    const clearBtn = csvName.nextElementSibling;
    if (clearBtn) clearBtn.hidden = !state.csvFile;
    refreshRecipients();
  });

  sendBtn.addEventListener("click", async () => {
    const blocked = missing();
    if (blocked) {
      errorBox.hidden = false;
      errorBox.textContent = blocked;
      toast(blocked, "err");
      return;
    }

    const template = state.templates.find((t) => String(t.id) === String(templateSelect.value));
    const category = String(template?.category || template?.type || "").toUpperCase();
    const count = state.recipientCount || 0;
    const marketing =
      category.includes("MARKET") ||
      category === "MARKETING";
    const confirmLines = [
      `Send “${template?.name || "template"}” to ${count} recipient${count === 1 ? "" : "s"}?`,
      category ? `Template category: ${category}.` : "",
      marketing
        ? "MARKETING templates share Meta’s per-customer daily cap — sends can look Sent then fail later. Cap and undeliverable failures mark permanently failed (not retried every 5 minutes). After many cap fails the rest of the list is skipped for today."
        : "",
    ]
      .filter(Boolean)
      .join("\n\n");
    if (!window.confirm(confirmLines)) return;

    sendBtn.disabled = true;
    sendBtn.textContent = "Starting…";
    errorBox.hidden = true;
    clear(statusBox).append(el("div.camp-recipients__empty", {}, ["Starting campaign…"]));

    try {
      const camp = await campaigns.create({
        number_id: numberSelect.value,
        template_id: templateSelect.value,
        name: nameInput.value.trim(),
        recipients_text: phonesArea.value,
        csv: state.csvFile,
        variables: { ...state.body },
        header_variables: { ...state.headerText },
        button_variables: { ...state.buttonVars },
        header_media_id: state.headerMedia?.media_id || "",
      });
      renderProgress(camp);
      toast(
        `Campaign #${camp.id} running in the background · ${camp.total} recipients. Open History anytime.`,
        "ok"
      );
      sendBtn.textContent = "Running…";
      pollCampaign(camp.id);
      setTab("history");
    } catch (err) {
      sendBtn.disabled = false;
      sendBtn.textContent = "Start campaign";
      clear(statusBox);
      errorBox.hidden = false;
      errorBox.textContent = err?.message || "Could not start campaign";
      toast(err?.message || "Could not start campaign", "err");
    }
  });

  loadNumbers();
}
