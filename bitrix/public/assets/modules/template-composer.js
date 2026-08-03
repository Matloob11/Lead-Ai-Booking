/**
 * Template composer: pick an approved template, fill it in, watch it build.
 *
 * A template is not a message the agent writes — it is a shape Meta approved,
 * with holes in it. The agent's job is to fill the holes correctly, and the
 * only way to be sure they have is to show them the result. So the left column
 * collects the values and the right column draws the message as the customer
 * will receive it, on a phone-sized canvas, as it is typed.
 *
 * Two callers, one component: replying inside an open chat, and opening a new
 * one from a number nobody has messaged yet. They differ only in whether a
 * recipient has to be asked for, and in which endpoint the send goes to.
 */

import { inbox, catalog } from "../api/api.js";
import { clear, debounce, el, formatBytes, modal } from "../core/dom.js";
import { icon } from "../core/icons.js";

const MAX_VISIBLE_BUTTONS = 3;

/** Media headers cannot be typed — a file has to be uploaded for them. */
const MEDIA_HEADERS = { IMAGE: "image", VIDEO: "video", DOCUMENT: "document" };

const ACCEPT = {
  IMAGE: "image/jpeg,image/png",
  VIDEO: "video/mp4,video/3gpp",
  DOCUMENT: ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt",
};

/* --------------------------------------------------------------- helpers */

const PLACEHOLDER = /\{\{(\d+)\}\}/g;

/** The distinct {{n}} in a string, in the order Meta will read them. */
function placeholdersIn(text) {
  const found = new Set();
  String(text || "").replace(PLACEHOLDER, (_, n) => found.add(n));
  return [...found].sort((a, b) => Number(a) - Number(b));
}

/**
 * WhatsApp's inline formatting, as DOM rather than HTML.
 *
 * Built node by node on purpose: the text is a template body from Meta and the
 * values are typed by an agent, and neither should ever reach innerHTML.
 */
const FORMATS = [
  { mark: "*", tag: "strong" },
  { mark: "_", tag: "em" },
  { mark: "~", tag: "s" },
  { mark: "```", tag: "code" },
];

function formatted(text) {
  const frag = document.createDocumentFragment();
  let rest = String(text || "");

  outer: while (rest) {
    for (const { mark, tag } of FORMATS) {
      if (!rest.startsWith(mark)) continue;
      const end = rest.indexOf(mark, mark.length);
      // An unclosed mark is just a character the agent typed.
      if (end > mark.length) {
        frag.append(el(tag, {}, [rest.slice(mark.length, end)]));
        rest = rest.slice(end + mark.length);
        continue outer;
      }
    }
    // Walk to the next character that could open a run, never past it.
    const next = rest.slice(1).search(/[*_~`]/);
    const take = next === -1 ? rest.length : next + 1;
    frag.append(document.createTextNode(rest.slice(0, take)));
    rest = rest.slice(take);
  }
  return frag;
}

/**
 * The template text with the agent's values in it. A hole they have not filled
 * yet stays visible as {{n}} and is tinted, so "what is left to do" is readable
 * off the preview instead of off an error message after they press send.
 */
function withValues(text, values) {
  const frag = document.createDocumentFragment();
  const source = String(text || "");
  let cursor = 0;

  PLACEHOLDER.lastIndex = 0;
  for (let match; (match = PLACEHOLDER.exec(source)); ) {
    if (match.index > cursor) frag.append(formatted(source.slice(cursor, match.index)));
    const value = (values[match[1]] || "").trim();
    frag.append(value ? document.createTextNode(value) : el("span.tplc-hole", {}, [match[0]]));
    cursor = match.index + match[0].length;
  }
  if (cursor < source.length) frag.append(formatted(source.slice(cursor)));
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
  URL: () => svg(["M10 13a5 5 0 007.5.5l3-3a5 5 0 00-7-7l-1.7 1.7", "M14 11a5 5 0 00-7.5-.5l-3 3a5 5 0 007 7l1.7-1.7"]),
  PHONE_NUMBER: () => svg(["M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012 4.2 2 2 0 014 2h3a2 2 0 012 1.7c.1.9.3 1.8.6 2.7a2 2 0 01-.4 2.1L8 9.8a16 16 0 006 6l1.3-1.2a2 2 0 012.1-.5c.9.3 1.8.5 2.7.6A2 2 0 0122 16.9z"]),
  COPY_CODE: () => svg(["M9 9h10v10H9z", "M5 15V5h10"]),
  QUICK_REPLY: () => svg(["M9 17l-5-5 5-5", "M20 18v-2a4 4 0 00-4-4H4"]),
};

const buttonIcon = (type) => (BUTTON_ICON[type] || BUTTON_ICON.QUICK_REPLY)();

/* -------------------------------------------------------------- the modal */

/**
 * @param {object}   options
 * @param {"reply"|"new"} options.mode
 * @param {object}   [options.conversation]  the chat to reply into (reply mode)
 * @param {object[]} [options.numbers]       numbers to choose from (new mode)
 * @param {function} options.templatesFor    (numberId) => Promise<template[]>
 * @param {function} options.onSent          (result) => void, after a send lands
 */
export function openTemplateComposer({ mode, conversation, numbers = [], templatesFor, onSent, findExisting, onOpenExisting }) {
  const isNew = mode === "new";

  const state = {
    numberId: isNew ? numbers[0]?.id ?? "" : conversation.number_id,
    templates: [],
    selected: null,
    body: {},        // {"1": "Ali"}
    headerText: {},  // same, for a TEXT header
    buttonVars: {},  // keyed by button index, for a URL ending in {{1}}
    headerMedia: null, // {media_id, name, size, previewUrl}
    uploading: false,
  };

  /* ---- left column: what to send ------------------------------------- */

  const search = el("input.tplc-search", { type: "search", placeholder: "Search templates…" });
  const list = el("div.tplc-list");
  const form = el("div.tplc-form");
  const error = el("div.alert.tplc-error", { hidden: true });
  const sendBtn = el("button.btn.btn--primary", { type: "button" }, [
    isNew ? "Start the chat" : "Send template",
  ]);

  const numberSelect = el(
    "select.field",
    // The warning's wording depends on which of our numbers is selected, so a
    // change here has to re-evaluate it.
    { onchange: () => { state.numberId = numberSelect.value; loadTemplates(); checkExisting(); } },
    numbers.map((n) => el("option", { value: n.id }, [n.title || n.phone_number]))
  );
  const phone = el("input.field", { type: "tel", placeholder: "971501234567" });

  /**
   * Warns when the typed customer already has a thread.
   *
   * The server keeps one conversation per (our number, customer), so sending
   * from the same number lands in the existing chat — but picking a different
   * one of our numbers opens a second thread, which is how a customer ends up
   * looking duplicated in the list. Saying so here is the only point where it
   * can still be avoided.
   */
  const dupNotice = el("div.tplc-dup", { hidden: true });

  const checkExisting = debounce(async () => {
    if (!isNew || typeof findExisting !== "function") return;

    const waId = phone.value.replace(/\D/g, "");
    if (waId.length < 8) {
      dupNotice.hidden = true;
      return;
    }

    let found;
    try {
      found = await findExisting(waId);
    } catch {
      return; // a failed lookup must not block a legitimate new chat
    }
    if (phone.value.replace(/\D/g, "") !== waId) return; // typed on since

    if (!found) {
      dupNotice.hidden = true;
      return;
    }

    const sameNumber = String(found.number_id) === String(state.numberId);
    clear(dupNotice).append(
      el("div", {}, [
        sameNumber
          ? "Is customer ki chat pehle se maujood hai — template usi chat mein chala jayega, nayi chat nahi banegi."
          : `Is customer ki chat pehle se maujood hai, magar ${found.number_title} par. Doosre number se bhejne par alag chat banegi.`,
      ]),
      // Deliberately not .btn--ghost: the theme forces white text on that class
      // with !important, which is invisible on this amber plate.
      el("button.tplc-dup__btn", {
        type: "button",
        onclick: () => {
          dialog.close();
          onOpenExisting?.(found.id);
        },
      }, ["Wahi chat kholein"])
    );
    dupNotice.hidden = false;
  }, 350);

  /* ---- right column: what they will see ------------------------------ */

  const previewBubble = el("div.tplc-bubble");
  const previewButtons = el("div.tplc-btns");
  const phoneFrame = el("div.tplc-phone", {}, [
    el("div.tplc-phone__bar", {}, [
      el("span.tplc-phone__avatar"),
      el("div.tplc-phone__who", {}, [
        el("div.tplc-phone__name", {}, [recipientLabel()]),
        el("div.tplc-phone__sub", {}, ["online"]),
      ]),
    ]),
    el("div.tplc-phone__screen", {}, [el("div.tplc-out", {}, [previewBubble, previewButtons])]),
  ]);

  function recipientLabel() {
    if (!isNew) return conversation.contact?.name || conversation.contact?.wa_id || "Customer";
    return phone.value.trim() || "New contact";
  }

  /* ---- template list -------------------------------------------------- */

  function renderList() {
    const term = search.value.trim().toLowerCase();
    const matches = state.templates.filter(
      (t) =>
        !term ||
        t.name.toLowerCase().includes(term) ||
        (t.body_text || "").toLowerCase().includes(term)
    );

    clear(list);
    if (!state.templates.length) {
      list.append(el("div.tplc-empty", {}, ["This number has no approved templates."]));
      return;
    }
    if (!matches.length) {
      list.append(el("div.tplc-empty", {}, ["No template matches that."]));
      return;
    }

    for (const template of matches) {
      const marketing = (template.category || "").toUpperCase() === "MARKETING";
      list.append(
        el(
          "button.tplc-item",
          {
            type: "button",
            class: state.selected?.id === template.id ? "is-selected" : "",
            onclick: () => select(template),
          },
          [
            el("div.tplc-item__top", {}, [
              el("span.tplc-item__name", {}, [template.name]),
              el("span.tplc-item__lang", {}, [template.language || ""]),
            ]),
            el("div.tplc-item__text", {}, [(template.body_text || "").slice(0, 90)]),
            el("div.tplc-item__tags", {}, [
              el(
                "span.tplc-tag",
                { class: marketing ? "tplc-tag--marketing" : "tplc-tag--utility" },
                [template.category || "TEMPLATE"]
              ),
              template.variable_count
                ? el("span.tplc-tag.tplc-tag--vars", {}, [`${template.variable_count} field${template.variable_count > 1 ? "s" : ""}`])
                : null,
              template.buttons?.length
                ? el("span.tplc-tag.tplc-tag--btns", {}, [`${template.buttons.length} button${template.buttons.length > 1 ? "s" : ""}`])
                : null,
              template.requires_header_media
                ? el("span.tplc-tag.tplc-tag--media", {}, [MEDIA_HEADERS[template.header.format]])
                : null,
            ]),
          ]
        )
      );
    }
  }

  /* ---- the fields a template asks for --------------------------------- */

  function select(template) {
    state.selected = template;
    state.body = {};
    state.headerText = {};
    state.buttonVars = {};
    state.headerMedia = null;
    renderList();
    renderForm();
    renderPreview();
  }

  function textField(label, hint, onInput) {
    const input = el("input.field", { type: "text", placeholder: hint, oninput: onInput });
    return { input, node: el("label.tplc-field", {}, [el("span", {}, [label]), input]) };
  }

  function renderForm() {
    clear(form);
    const template = state.selected;
    if (!template) {
      form.append(el("div.tplc-empty", {}, ["Choose a template to fill it in."]));
      sendBtn.disabled = true;
      return;
    }

    form.append(el("div.tplc-form__title", {}, [template.name]));

    const header = template.header;

    if (template.requires_header_media) {
      form.append(mediaField(header.format));
    } else if (header?.format === "TEXT") {
      for (const n of placeholdersIn(header.text)) {
        form.append(
          textField(`Header {{${n}}}`, "Text for the header", (event) => {
            state.headerText[n] = event.target.value;
            renderPreview();
          }).node
        );
      }
    }

    for (const n of placeholdersIn(template.body_text)) {
      form.append(
        textField(`Variable {{${n}}}`, sampleFor(template.body_text, n), (event) => {
          state.body[n] = event.target.value;
          renderPreview();
        }).node
      );
    }

    const asksForNothing =
      !template.variable_count &&
      !template.requires_header_media &&
      !header?.variable_count &&
      !(template.buttons || []).some((b) => b.variable_count);
    if (asksForNothing) {
      form.append(el("div.tplc-note", {}, ["This template has nothing to fill in — it sends as written."]));
    }

    // A URL button whose link ends in {{1}} takes a value per message — the
    // only part of a button the sender may change.
    for (const button of template.buttons || []) {
      if (!button.variable_count) continue;
      form.append(
        textField(`Link for "${button.text}"`, "Value for the end of the link", (event) => {
          state.buttonVars[String(button.index)] = event.target.value;
          renderPreview();
        }).node
      );
    }

    if (template.buttons?.length) {
      form.append(
        el("div.tplc-note", {}, [
          `${template.buttons.length} button${template.buttons.length > 1 ? "s are" : " is"} `,
          "part of the approved template. Their labels cannot be changed here.",
        ])
      );
    }

    refreshSendState();
  }

  /**
   * The few words on either side of a placeholder, as the input's hint.
   * "Hello {{1}}, this is {{2}} from A7" then asks for "Hello …, this is" —
   * which tells the agent what belongs there far better than "Variable 1".
   */
  function sampleFor(text, n) {
    const source = String(text || "");
    const at = source.indexOf(`{{${n}}}`);
    if (at === -1) return `Value for {{${n}}}`;
    const before = source.slice(Math.max(0, at - 24), at).trimStart();
    const after = source.slice(at + `{{${n}}}`.length, at + `{{${n}}}`.length + 16).trimEnd();
    return `…${before}▮${after}…`.replace(/\s+/g, " ");
  }

  function mediaField(format) {
    const kind = MEDIA_HEADERS[format];
    const status = el("div.tplc-media__status", {}, [`This template needs a ${kind} header.`]);
    const picker = el("input", { type: "file", accept: ACCEPT[format] || "", hidden: true });
    const pick = el("button.btn.btn--ghost.btn--sm", { type: "button", onclick: () => picker.click() }, [
      `Choose ${kind}`,
    ]);

    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      picker.value = "";
      if (!file) return;

      state.uploading = true;
      state.headerMedia = null;
      status.textContent = `Uploading ${file.name}…`;
      refreshSendState();
      renderPreview();

      try {
        const result = await inbox.uploadMedia(file, {
          conversationId: isNew ? undefined : conversation.id,
          numberId: isNew ? state.numberId : undefined,
        }).promise;

        state.headerMedia = {
          media_id: result.media_id,
          name: file.name,
          size: file.size,
          // Drawn from the local file, so the preview is the actual picture
          // rather than a round trip to fetch back what we just sent.
          previewUrl: format === "IMAGE" ? URL.createObjectURL(file) : "",
        };
        status.textContent = `${file.name} · ${formatBytes(file.size)}`;
      } catch (err) {
        status.textContent = `Upload failed: ${err.message}`;
      } finally {
        state.uploading = false;
        refreshSendState();
        renderPreview();
      }
    });

    return el("div.tplc-field.tplc-media", {}, [
      el("span", {}, [`${kind[0].toUpperCase()}${kind.slice(1)} header`]),
      el("div.tplc-media__row", {}, [pick, status]),
      picker,
    ]);
  }

  /* ---- the preview ---------------------------------------------------- */

  /**
   * Redraws the phone. Every field change routes through here, so this is also
   * where the Send button learns whether the template is complete — keeping the
   * two apart is what made the button stay disabled while the agent typed.
   */
  function renderPreview() {
    const template = state.selected;
    refreshSendState();
    clear(previewBubble);
    clear(previewButtons);

    if (!template) {
      previewBubble.classList.add("is-empty");
      previewBubble.append(el("div.tplc-bubble__hint", {}, ["Your message will appear here."]));
      return;
    }
    previewBubble.classList.remove("is-empty");

    const header = template.header;
    if (template.requires_header_media) {
      previewBubble.append(mediaPreview(header.format));
    } else if (header?.format === "TEXT" && header.text) {
      previewBubble.append(el("div.tplc-bubble__header", {}, [withValues(header.text, state.headerText)]));
    }

    previewBubble.append(el("div.tplc-bubble__body", {}, [withValues(template.body_text, state.body)]));

    if (template.footer_text) {
      previewBubble.append(el("div.tplc-bubble__footer", {}, [template.footer_text]));
    }

    previewBubble.append(
      el("div.tplc-bubble__meta", {}, [
        el("span", {}, [
          new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        ]),
        svg(["M1 13l4 4L13 7", "M8 13l4 4L22 7"], { size: 14 }),
      ])
    );

    const buttons = template.buttons || [];
    // WhatsApp shows the first three and folds the rest behind one row.
    for (const button of buttons.slice(0, MAX_VISIBLE_BUTTONS)) {
      previewButtons.append(
        el("div.tplc-btn", {}, [buttonIcon(button.type), el("span", {}, [button.text || "Button"])])
      );
    }
    if (buttons.length > MAX_VISIBLE_BUTTONS) {
      previewButtons.append(
        el("div.tplc-btn.tplc-btn--more", {}, [
          buttonIcon("QUICK_REPLY"),
          el("span", {}, ["See all options"]),
        ])
      );
    }
  }

  function mediaPreview(format) {
    if (format === "IMAGE" && state.headerMedia?.previewUrl) {
      return el("img.tplc-bubble__image", { src: state.headerMedia.previewUrl, alt: "" });
    }
    const label = state.headerMedia
      ? `${state.headerMedia.name} · ${formatBytes(state.headerMedia.size)}`
      : state.uploading
        ? "Uploading…"
        : `${MEDIA_HEADERS[format]} header — not chosen yet`;
    return el("div.tplc-bubble__media", { class: state.headerMedia ? "" : "is-missing" }, [
      svg(
        format === "VIDEO"
          ? ["M23 7l-7 5 7 5V7z", "M1 5h15v14H1z"]
          : format === "DOCUMENT"
            ? ["M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z", "M14 2v6h6"]
            : ["M3 3h18v18H3z", "M3 15l5-5 4 4 3-3 6 6"],
        { size: 18 }
      ),
      el("span", {}, [label]),
    ]);
  }

  /* ---- validity and sending ------------------------------------------ */

  function missing() {
    const template = state.selected;
    if (!template) return "Choose a template.";
    if (isNew && !phone.value.replace(/\D/g, "")) return "Enter the customer's number.";
    if (state.uploading) return "Wait for the upload to finish.";
    if (template.requires_header_media && !state.headerMedia) {
      return `Choose the ${MEDIA_HEADERS[template.header.format]} for the header.`;
    }
    const header = template.header;
    if (header?.format === "TEXT" && placeholdersIn(header.text).some((n) => !(state.headerText[n] || "").trim())) {
      return "Fill in the header field.";
    }
    if (placeholdersIn(template.body_text).some((n) => !(state.body[n] || "").trim())) {
      return "Fill in every field.";
    }
    const button = (template.buttons || []).find(
      (b) => b.variable_count && !(state.buttonVars[String(b.index)] || "").trim()
    );
    if (button) return `Fill in the link for "${button.text}".`;
    return "";
  }

  function refreshSendState() {
    sendBtn.disabled = Boolean(missing());
  }

  sendBtn.addEventListener("click", async () => {
    const blocked = missing();
    error.hidden = !blocked;
    if (blocked) {
      error.textContent = blocked;
      return;
    }

    const payload = {
      template_id: state.selected.id,
      variables: state.body,
      header_variables: state.headerText,
      button_variables: state.buttonVars,
      header_media_id: state.headerMedia?.media_id || "",
    };

    sendBtn.disabled = true;
    const label = sendBtn.textContent;
    sendBtn.textContent = "Sending…";
    try {
      const result = isNew
        ? await inbox.start({
            ...payload,
            number_id: state.numberId,
            to: phone.value.replace(/\D/g, ""),
          })
        : await inbox.sendTemplate(conversation.id, payload);

      dialog.close();
      await onSent?.(result);
    } catch (err) {
      sendBtn.disabled = false;
      sendBtn.textContent = label;
      error.hidden = false;
      error.textContent = err.message;
    }
  });

  /* ---- assembly ------------------------------------------------------- */

  search.addEventListener("input", debounce(renderList, 150));
  phone.addEventListener("input", () => {
    phoneFrame.querySelector(".tplc-phone__name").textContent = recipientLabel();
    refreshSendState();
    checkExisting();
  });

  const left = el("div.tplc-left", {}, [
    isNew
      ? el("div.tplc-recipient", {}, [
          el("label.tplc-field", {}, [el("span", {}, ["From"]), numberSelect]),
          el("label.tplc-field", {}, [el("span", {}, ["To"]), phone]),
          dupNotice,
        ])
      : null,
    search,
    list,
    form,
    error,
    el("div.tplc-actions", {}, [sendBtn]),
  ]);

  const body = el("div.modal__body.tplc", {}, [left, el("div.tplc-right", {}, [phoneFrame])]);
  const dialog = modal(isNew ? "New contact" : "Send a template", body, { wide: true });

  async function loadTemplates() {
    state.selected = null;
    clear(list).append(el("div.tplc-empty", {}, ["Loading templates…"]));
    renderForm();
    renderPreview();
    try {
      state.templates = await templatesFor(state.numberId);
    } catch (err) {
      clear(list).append(el("div.tplc-empty", {}, [`Could not load templates: ${err.message}`]));
      return;
    }
    renderList();
  }

  renderForm();
  renderPreview();
  loadTemplates();
  return dialog;
}

export function openTemplateManager({ onUseTemplate } = {}) {
  const body = el("div.modal__body.na", {}, [el("div.na-note", {}, ["Loading templates from Meta…"])]);
  const dialog = modal("Templates Management Center", body, { wide: true });

  let templates = [];
  let filterStatus = "";
  let searchTerm = "";

  const search = el("input.na-search", {
    type: "search",
    placeholder: "Find template by name or text…",
  });

  const statusSelect = el("select.na-picker", { style: "width: 140px;" }, [
    el("option", { value: "" }, ["All Statuses"]),
    el("option", { value: "APPROVED" }, ["Approved"]),
    el("option", { value: "PENDING" }, ["Pending"]),
    el("option", { value: "REJECTED" }, ["Rejected"]),
  ]);

  const syncBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, [
    icon("refresh", { size: 14 }),
    " Sync from Meta",
  ]);

  const createBtn = el("button.btn.btn--primary.btn--sm", { type: "button" }, [
    icon("plus", { size: 14 }),
    " Create New Template",
  ]);

  const summary = el("div.na-summary");
  const listContainer = el("div.na-rows");

  const toolbar = el("div.na-toolbar", { style: "align-items: center;" }, [
    search,
    statusSelect,
    syncBtn,
    createBtn,
  ]);

  search.addEventListener("input", () => {
    searchTerm = search.value.trim().toLowerCase();
    render();
  });

  statusSelect.addEventListener("change", () => {
    filterStatus = statusSelect.value;
    render();
  });

  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    syncBtn.textContent = "Syncing…";
    try {
      await catalog.syncTemplates();
      await fetchTemplates();
    } catch (err) {
      alert(`Sync failed: ${err.message}`);
    } finally {
      syncBtn.disabled = false;
      syncBtn.replaceChildren(icon("refresh", { size: 14 }), " Sync from Meta");
    }
  });

  createBtn.addEventListener("click", () => {
    openCreateTemplateModal({
      onCreated: async () => {
        await fetchTemplates();
      },
    });
  });

  async function fetchTemplates() {
    clear(body).append(el("div.na-note", {}, ["Loading templates from Meta…"]));
    try {
      templates = await catalog.allTemplates();
      renderMain();
    } catch (err) {
      clear(body).append(el("div.alert", {}, [`Failed to load templates: ${err.message}`]));
    }
  }

  function renderMain() {
    clear(body).append(toolbar, summary, listContainer);
    render();
  }

  function render() {
    clear(listContainer);
    const approvedCount = templates.filter((t) => t.status === "APPROVED").length;
    const pendingCount = templates.filter((t) => t.status === "PENDING").length;
    const rejectedCount = templates.filter((t) => t.status === "REJECTED").length;

    const filtered = templates.filter((t) => {
      const matchStatus = !filterStatus || t.status === filterStatus;
      const matchText =
        !searchTerm ||
        t.name.toLowerCase().includes(searchTerm) ||
        (t.body_text || "").toLowerCase().includes(searchTerm);
      return matchStatus && matchText;
    });

    clear(summary).append(
      `${templates.length} total templates · `,
      el("span.tpl-stat-approved", { style: "color: #10b981; font-weight: 600;" }, [`${approvedCount} Approved`]),
      " · ",
      el("span.tpl-stat-pending", { style: "color: #f59e0b; font-weight: 600;" }, [`${pendingCount} Pending`]),
      rejectedCount ? ` · ${rejectedCount} Rejected` : "",
      searchTerm || filterStatus ? ` · showing ${filtered.length}` : ""
    );

    if (!filtered.length) {
      listContainer.append(el("div.tplc-empty", {}, ["No templates match your filters."]));
      return;
    }

    for (const t of filtered) {
      const isApproved = t.status === "APPROVED";
      const isPending = t.status === "PENDING";
      const isRejected = t.status === "REJECTED";

      const statusTone = isApproved ? "ok" : isPending ? "warn" : isRejected ? "bad" : "";
      const statusLabel = isApproved ? "APPROVED" : isPending ? "PENDING (Under Meta Review)" : isRejected ? "REJECTED" : t.status;

      const card = el("div.na-row.tpl-card", {}, [
        el("div.na-head", {}, [
          el("div.na-who", {}, [
            el("div.na-title", {}, [t.name]),
            el("div.na-phone", {}, [`Language: ${t.language} · Category: ${t.category}`]),
          ]),
          el("div.na-flags", {}, [
            el("span.na-badge", { class: `na-badge--${statusTone}` }, [statusLabel]),
          ]),
        ]),
        el("div.na-body", { style: "grid-template-columns: 1fr;" }, [
          el("div.tplc-item__text", { style: "white-space: pre-wrap; font-size: 13px;" }, [t.body_text || "—"]),
          t.footer_text ? el("div.tplc-bubble__footer", { style: "font-size: 11px; opacity: 0.7;" }, [t.footer_text]) : null,
        ]),
        el("div.na-foot", {}, [
          isApproved
            ? el("button.btn.btn--primary.btn--sm", {
                type: "button",
                onclick: () => {
                  dialog.close();
                  onUseTemplate?.(t);
                },
              }, ["Use in Chat"])
            : el("span.na-status", {}, [isPending ? "Meta is reviewing this template (1-2 mins)" : "Template not available for sending"]),
        ]),
      ]);

      listContainer.append(card);
    }
  }

  fetchTemplates();
  return dialog;
}

export function openCreateTemplateModal({ onCreated } = {}) {
  const nameInput = el("input.field", {
    type: "text",
    placeholder: "e.g. property_viewing_offer",
  });

  const categorySelect = el("select.field", {}, [
    el("option", { value: "MARKETING" }, ["MARKETING (Promotions, Offers, Re-engagement)"]),
    el("option", { value: "UTILITY" }, ["UTILITY (Order updates, Appointments, Account alerts)"]),
  ]);

  const langSelect = el("select.field", {}, [
    el("option", { value: "en" }, ["English (en)"]),
    el("option", { value: "ar" }, ["Arabic (ar)"]),
    el("option", { value: "ur" }, ["Urdu (ur)"]),
  ]);

  const headerInput = el("input.field", { type: "text", placeholder: "Header text (optional)" });
  const bodyTextarea = el("textarea.field", { rows: 4, placeholder: "Hello {{1}}, thank you for contacting A7 Group. Your appointment is set for {{2}}." });
  const footerInput = el("input.field", { type: "text", placeholder: "Footer text e.g. A7 Real Estate (optional)" });
  const buttonsInput = el("input.field", { type: "text", placeholder: "Quick reply buttons comma separated e.g. Interested, Call Me" });

  const addVar1 = el("button.btn.btn--ghost.btn--sm", { type: "button", style: "padding: 2px 8px; font-size: 11px;" }, ["+ {{1}}"]);
  const addVar2 = el("button.btn.btn--ghost.btn--sm", { type: "button", style: "padding: 2px 8px; font-size: 11px;" }, ["+ {{2}}"]);

  addVar1.addEventListener("click", () => {
    bodyTextarea.value += " {{1}}";
    updatePreview();
  });
  addVar2.addEventListener("click", () => {
    bodyTextarea.value += " {{2}}";
    updatePreview();
  });

  const nameHint = el("span", { style: "font-size: 11px; opacity: 0.7;" }, ["Format: lowercase and underscores only"]);

  nameInput.addEventListener("input", () => {
    nameInput.value = nameInput.value.toLowerCase().replace(/[^\w]+/g, "_");
    nameHint.textContent = `Meta identifier: ${nameInput.value || "template_name"}`;
    updatePreview();
  });

  headerInput.addEventListener("input", updatePreview);
  bodyTextarea.addEventListener("input", updatePreview);
  footerInput.addEventListener("input", updatePreview);

  const previewBody = el("div.tplc-bubble");
  const phoneFrame = el("div.tplc-phone", {}, [
    el("div.tplc-phone__bar", {}, [
      el("span.tplc-phone__avatar"),
      el("div.tplc-phone__who", {}, [
        el("div.tplc-phone__name", {}, ["Live Preview"]),
        el("div.tplc-phone__sub", {}, ["WhatsApp Template"]),
      ]),
    ]),
    el("div.tplc-phone__screen", {}, [el("div.tplc-out", {}, [previewBody])]),
  ]);

  function updatePreview() {
    clear(previewBody);
    if (headerInput.value.trim()) {
      previewBody.append(el("div.tplc-bubble__header", {}, [headerInput.value.trim()]));
    }
    previewBody.append(el("div.tplc-bubble__body", {}, [bodyTextarea.value.trim() || "Your template message body text will appear here..."]));
    if (footerInput.value.trim()) {
      previewBody.append(el("div.tplc-bubble__footer", {}, [footerInput.value.trim()]));
    }
  }

  const errorEl = el("div.alert", { hidden: true });
  const submitBtn = el("button.btn.btn--primary", { type: "button" }, [
    icon("send", { size: 14 }),
    " Submit Template to Meta",
  ]);

  const leftForm = el("div.tplc-form", { style: "gap: 10px;" }, [
    el("label.tplc-field", {}, [el("span", {}, ["Template Name"]), nameInput, nameHint]),
    el("label.tplc-field", {}, [el("span", {}, ["Category"]), categorySelect]),
    el("label.tplc-field", {}, [el("span", {}, ["Language"]), langSelect]),
    el("label.tplc-field", {}, [el("span", {}, ["Header Text (Optional)"]), headerInput]),
    el("label.tplc-field", {}, [
      el("div", { style: "display: flex; justify-content: space-between; align-items: center;" }, [
        el("span", {}, ["Body Text"]),
        el("div", { style: "display: flex; gap: 4px;" }, [addVar1, addVar2]),
      ]),
      bodyTextarea,
    ]),
    el("label.tplc-field", {}, [el("span", {}, ["Footer Text (Optional)"]), footerInput]),
    el("label.tplc-field", {}, [el("span", {}, ["Quick Reply Buttons (Comma separated, max 3)"]), buttonsInput]),
    errorEl,
    el("div.tplc-actions", {}, [submitBtn]),
  ]);

  const body = el("div.modal__body.tplc", {}, [leftForm, el("div.tplc-right", {}, [phoneFrame])]);
  const dialog = modal("Create New WhatsApp Template", body, { wide: true });

  updatePreview();

  submitBtn.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    const bodyText = bodyTextarea.value.trim();

    if (!name) {
      errorEl.textContent = "Please enter a valid template name.";
      errorEl.hidden = false;
      return;
    }
    if (!bodyText) {
      errorEl.textContent = "Please enter the template body text.";
      errorEl.hidden = false;
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting to Meta…";
    errorEl.hidden = true;

    try {
      await catalog.createTemplate({
        name,
        category: categorySelect.value,
        language: langSelect.value,
        header_text: headerInput.value.trim(),
        body_text: bodyText,
        footer_text: footerInput.value.trim(),
        buttons: buttonsInput.value.trim(),
      });

      alert("Template submitted successfully to Meta! Status: PENDING (Meta usually approves in 1-2 minutes).");
      dialog.close();
      onCreated?.();
    } catch (err) {
      submitBtn.disabled = false;
      submitBtn.replaceChildren(icon("send", { size: 14 }), " Submit Template to Meta");
      errorEl.textContent = err.message || "Failed to submit template to Meta.";
      errorEl.hidden = false;
    }
  });

  return dialog;
}
