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
import {
  clearTemplateCaches,
  readNumbersCache,
  readTemplatesCache,
  writeNumbersCache,
  writeTemplatesCache,
} from "./template-cache.js";
import { clear, debounce, el, formatBytes, modal } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { numberNameWithDial } from "../core/number-label.js";

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

/** The little picture WhatsApp draws for a header that is not text. */
function mediaGlyph(format) {
  return svg(
    format === "VIDEO"
      ? ["M23 7l-7 5 7 5V7z", "M1 5h15v14H1z"]
      : format === "DOCUMENT"
        ? ["M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z", "M14 2v6h6"]
        : ["M3 3h18v18H3z", "M3 15l5-5 4 4 3-3 6 6"],
    { size: 18 }
  );
}

/* -------------------------------------------------------------- the modal */

/**
 * @param {object}   options
 * @param {"reply"|"new"} options.mode
 * @param {object}   [options.conversation]  the chat to reply into (reply mode)
 * @param {object[]} [options.numbers]       numbers to choose from (new mode)
 * @param {function} options.templatesFor    (numberId) => Promise<template[]>
 * @param {function} options.onSent          (result) => void, after a send lands
 */
/**
 * @param {string} [options.to]  the customer's number, already known.
 *   Set when the agent arrived from a CRM record rather than from this panel:
 *   they clicked the WhatsApp icon beside a lead's phone number, and being
 *   asked to type that same number back in would be the panel forgetting why
 *   it was opened.
 */
export function openTemplateComposer({ mode, conversation, numbers = [], templatesFor, onSent, findExisting, onOpenExisting, to = "" }) {
  const isNew = mode === "new";

  const usable = numbers.find((n) => !n.send_blocked) || numbers[0];
  const state = {
    numberId: isNew ? usable?.id ?? "" : conversation.number_id,
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

  const fromWarn = el("div.tplc-from-warn", { hidden: true }, [
    "This From-number cannot send — the provider banned it. Pick another number.",
  ]);

  function fromLabel(number) {
    const base = numberNameWithDial(number);
    return number.send_blocked ? `${base} — cannot send` : base;
  }

  function paintFromOptions() {
    const current = String(state.numberId);
    clear(numberSelect);
    for (const n of numbers) {
      numberSelect.append(el("option", { value: n.id }, [fromLabel(n)]));
    }
    const keep = numbers.some((n) => String(n.id) === current);
    numberSelect.value = keep ? current : String(usable?.id || numbers[0]?.id || "");
    state.numberId = numberSelect.value;
    refreshFromWarn();
  }

  function refreshFromWarn() {
    const chosen = numbers.find((n) => String(n.id) === String(state.numberId));
    fromWarn.hidden = !chosen?.send_blocked;
  }

  const numberSelect = el(
    "select.field",
    // The warning's wording depends on which of our numbers is selected, so a
    // change here has to re-evaluate it.
    {
      onchange: () => {
        state.numberId = numberSelect.value;
        refreshFromWarn();
        loadTemplates();
        checkExisting();
      },
    },
  );
  // Reply mode is given no `numbers` list. Painting the From picker there
  // emptied numberId and the next fetch became /catalog/numbers//templates/.
  if (isNew) paintFromOptions();
  const phone = el("input.field", {
    type: "tel",
    placeholder: "971501234567",
    value: String(to || "").replace(/\D/g, ""),
  });

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
          ? "This customer already has a chat on this number. The template will go in that chat, not a new one."
          : `This customer already has a chat on ${found.number_title}. Sending from a different number opens a second chat.`,
      ]),
      // Deliberately not .btn--ghost: the theme forces white text on that class
      // with !important, which is invisible on this amber plate.
      el("button.tplc-dup__btn", {
        type: "button",
        onclick: () => {
          dialog.close();
          onOpenExisting?.(found.id);
        },
      }, ["Open that chat"])
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
      if (/network banned/i.test(err.message || "")) {
        const chosen = numbers.find((n) => String(n.id) === String(state.numberId));
        if (chosen) chosen.send_blocked = true;
        paintFromOptions();
        numberSelect.focus();
        numberSelect.scrollIntoView({ block: "nearest" });
      }
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
          fromWarn,
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
      state.templates = await templatesFor(state.numberId, conversation);
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

function ensureTemplateCenterCss() {
  const href = "/app/assets/modules/template-center.css";
  if (document.querySelector(`link[href="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
}

export function openTemplateManager({ onUseTemplate, isAdmin = false } = {}) {
  ensureTemplateCenterCss();

  const body = el("div.modal__body.tmc", {}, [
    el("div.tmc-loading", {}, ["Loading templates…"]),
  ]);
  const dialog = modal("Message templates", body, { wide: true });
  dialog.box.classList.add("tmc-modal");

  let templates = [];
  let numbers = [];
  let filterStatus = "";
  let filterWaba = "";
  let searchTerm = "";

  const search = el("input.tmc-search", {
    type: "search",
    placeholder: "Find template by name or text…",
    "aria-label": "Find template by name or text",
  });

  // Templates belong to a business account and several numbers share one, so
  // an agent covering four numbers otherwise reads one undifferentiated list
  // and cannot tell which template can be sent from which phone.
  const numberSelect = el("select.tmc-picker", { "aria-label": "Filter by number" }, [
    el("option", { value: "" }, ["All my numbers"]),
  ]);

  const notice = el("p.tmc-notice", { hidden: true });
  const unreachableNote = el("div.tmc-notice.tmc-notice--warn", { hidden: true });

  /** Whichever of the caller's numbers sit on a template's business account. */
  const numbersFor = (wabaId) =>
    numbers.filter((n) => n.waba_business_id && n.waba_business_id === wabaId);

  const numberLabel = (wabaId) => {
    const shared = numbersFor(wabaId);
    if (!shared.length) return "";
    return shared.map((n) => n.phone_number || n.title || n.label).join(", ");
  };

  const statusSelect = el("select.tmc-picker", { "aria-label": "Filter by status" }, [
    el("option", { value: "" }, ["All statuses"]),
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
    " Create new template",
  ]);

  const stats = el("div.tmc-stats");
  const listContainer = el("div.tmc-list");
  const lead = el("p.tmc-lead", {}, [
    "Create submits straight to Meta. Sync is only to refresh review status (Pending → Approved).",
  ]);

  const toolbar = el("div.tmc-toolbar", {}, [
    search,
    numberSelect,
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

  numberSelect.addEventListener("change", () => {
    filterWaba = numberSelect.value;
    render();
  });

  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    clear(syncBtn).append("Syncing…");
    notice.hidden = true;
    try {
      const result = await catalog.syncTemplates(filterWaba || "");
      if (result?.sync === "started") {
        clear(notice).append(
          "Sync is running across every number. Statuses refresh in a moment — Pending usually becomes Approved within a minute."
        );
        notice.className = "tmc-notice tmc-notice--ok";
        notice.hidden = false;
        clearTemplateCaches();
        setTimeout(() => fetchTemplates({ force: true, silent: true }).catch(() => {}), 8000);
        setTimeout(() => fetchTemplates({ force: true, silent: true }).catch(() => {}), 25000);
        return;
      }
      clearTemplateCaches();
      await fetchTemplates({ force: true });
      // Said out loud, because the common outcome of a successful sync is that
      // nothing on screen changes, which reads exactly like a sync that failed.
      const count = Number(result?.templates);
      const skipped = Number(result?.wabas_failed) || 0;
      let line = Number.isFinite(count)
        ? `Refreshed from Meta — ${count} template${count === 1 ? "" : "s"} on this Official key.`
        : "Refreshed from Meta.";
      if (skipped) {
        line += ` ${skipped} extra business account${skipped === 1 ? "" : "s"} sit on a different WhatsApp provider and were skipped. Templates already here stay available.`;
      }
      clear(notice).append(line);
      notice.className = skipped ? "tmc-notice tmc-notice--warn" : "tmc-notice tmc-notice--ok";
      notice.hidden = false;
    } catch (err) {
      // In the panel rather than in a browser alert: this screen lives inside
      // two nested iframes, and "An embedded page at … says" is not a sentence
      // that tells anybody what went wrong.
      clear(notice).append(`Could not refresh from Meta: ${err.message}`);
      notice.className = "tmc-notice tmc-notice--bad";
      notice.hidden = false;
    } finally {
      syncBtn.disabled = false;
      syncBtn.replaceChildren(icon("refresh", { size: 14 }), " Sync from Meta");
    }
  });

  createBtn.addEventListener("click", () => {
    openCreateTemplateModal({
      numbers,
      isAdmin,
      onCreated: async (summary) => {
        let line =
          "Submitted to Meta. It is already in this list as Pending — no Sync needed. Review usually finishes in a minute or two; press Sync from Meta only to refresh the status.";
        if (summary && typeof summary.created === "number") {
          line = `Submitted to Meta on ${summary.created} business account${summary.created === 1 ? "" : "s"}`;
          if (summary.skipped) line += ` · ${summary.skipped} already had it`;
          if (summary.failed) line += ` · ${summary.failed} failed`;
          line += ". Pending until Meta approves — Sync refreshes status.";
        }
        clear(notice).append(line);
        notice.className = "tmc-notice tmc-notice--ok";
        notice.hidden = false;
        // Do not block the UI on a full list reload — refresh quietly.
        clearTemplateCaches();
        fetchTemplates({ force: true, silent: true }).catch(() => {});
      },
    });
  });

  async function pullLiveLists() {
    const [rows, numberRows] = await Promise.all([
      catalog.allTemplates(),
      catalog.numbers().catch(() => []),
    ]);
    templates = Array.isArray(rows) ? rows : [];
    numbers = Array.isArray(numberRows) ? numberRows : [];
    writeTemplatesCache(templates);
    writeNumbersCache(numbers);
  }

  async function fetchTemplates({ force = false, silent = false } = {}) {
    const cachedT = readTemplatesCache();
    const cachedN = readNumbersCache();
    const haveCache = Boolean(cachedT?.rows?.length);

    if (haveCache && !force) {
      templates = cachedT.rows;
      numbers = Array.isArray(cachedN?.rows) ? cachedN.rows : numbers;
      renderMain();
      // Background refresh — keep showing the cached list if the network is slow.
      pullLiveLists()
        .then(() => {
          if (dialog.box?.isConnected) renderMain();
        })
        .catch(() => {});
      return;
    }

    if (!silent) {
      clear(body).append(el("div.tmc-loading", {}, ["Loading templates…"]));
    }
    try {
      await pullLiveLists();
      renderMain();
    } catch (err) {
      if (haveCache) {
        templates = cachedT.rows;
        numbers = Array.isArray(cachedN?.rows) ? cachedN.rows : [];
        renderMain();
        clear(notice).append(`Showing saved list — live refresh failed: ${err.message}`);
        notice.className = "tmc-notice tmc-notice--warn";
        notice.hidden = false;
        return;
      }
      clear(body).append(el("div.tmc-notice.tmc-notice--bad", {}, [`Failed to load templates: ${err.message}`]));
    }
  }

  function renderNumberFilter() {
    const chosen = numberSelect.value;
    clear(numberSelect).append(el("option", { value: "" }, ["All my numbers"]));

    const seen = new Set();
    for (const number of numbers) {
      if (!number.waba_business_id || seen.has(number.waba_business_id)) continue;
      seen.add(number.waba_business_id);
      const onIt = templates.filter((t) => t.waba_business_id === number.waba_business_id).length;
      numberSelect.append(
        el("option", { value: number.waba_business_id }, [
          `${numberLabel(number.waba_business_id) || number.title} (${onIt})`,
        ])
      );
    }
    numberSelect.value = seen.has(chosen) ? chosen : "";
    filterWaba = numberSelect.value;
  }

  function paintUnreachable() {
    const bad = numbers.filter((n) => n.template_sync_error);
    if (!bad.length) {
      unreachableNote.hidden = true;
      return;
    }
    // Names the numbers, not "this Business ID": with a hundred numbers on
    // the account, a warning that does not say which one is only noise — and
    // quotes the gateway, because "Invalid WhatsApp configuration" has so far
    // always meant a mistyped Business ID, not a key problem.
    const one = bad.length === 1;
    clear(unreachableNote).append(
      el("strong", {}, [`${bad.length} number${one ? "" : "s"} cannot list templates.`]),
      ` The gateway does not know the Business ID on file, so nothing can be synced or created for ${one ? "it" : "them"} until the ID is corrected${isAdmin ? " in Numbers Management" : ""}. Every other number here is unaffected.`,
      el(
        "ul.tmc-notice__list",
        {},
        bad.map((n) => {
          const { phone, name } = formatWaNumber(n);
          return el("li", {}, [
            el("strong", {}, [phone]),
            [name, n.account_username].filter(Boolean).map((bit) => ` · ${bit}`).join(""),
            ` — "${n.template_sync_error}"`,
          ]);
        })
      )
    );
    unreachableNote.hidden = false;
  }

  function renderMain() {
    paintUnreachable();
    clear(body).append(lead, toolbar, unreachableNote, notice, stats, listContainer);
    renderNumberFilter();
    render();
  }

  function render() {
    clear(listContainer);
    const approvedCount = templates.filter((t) => t.status === "APPROVED").length;
    const pendingCount = templates.filter((t) => t.status === "PENDING").length;
    const rejectedCount = templates.filter((t) => t.status === "REJECTED").length;

    const filtered = templates.filter((t) => {
      const matchStatus = !filterStatus || t.status === filterStatus;
      const matchNumber = !filterWaba || t.waba_business_id === filterWaba;
      const matchText =
        !searchTerm ||
        t.name.toLowerCase().includes(searchTerm) ||
        (t.body_text || "").toLowerCase().includes(searchTerm);
      return matchStatus && matchNumber && matchText;
    });

    const totalLabel = searchTerm || filterStatus || filterWaba ? "Showing" : "Total";
    const totalValue = searchTerm || filterStatus || filterWaba ? filtered.length : templates.length;
    clear(stats).append(
      el("div.tmc-stat", {}, [
        el("strong", {}, [String(totalValue)]),
        el("span", {}, [totalLabel]),
      ]),
      el("div.tmc-stat.tmc-stat--ok", {}, [
        el("strong", {}, [String(approvedCount)]),
        el("span", {}, ["Approved"]),
      ]),
      el("div.tmc-stat.tmc-stat--warn", {}, [
        el("strong", {}, [String(pendingCount)]),
        el("span", {}, ["Pending"]),
      ]),
      el("div.tmc-stat.tmc-stat--bad", {}, [
        el("strong", {}, [String(rejectedCount)]),
        el("span", {}, ["Rejected"]),
      ])
    );

    if (!filtered.length) {
      listContainer.append(el("div.tmc-empty", {}, ["No templates match your filters."]));
      return;
    }

    for (const t of filtered) {
      const isApproved = t.status === "APPROVED";
      const isPending = t.status === "PENDING";
      const isRejected = t.status === "REJECTED";
      const statusTone = isApproved ? "ok" : isPending ? "warn" : isRejected ? "bad" : "";
      const statusLabel = isApproved
        ? "Approved"
        : isPending
          ? "Pending review"
          : isRejected
            ? "Rejected"
            : t.status;

      const phones = numberLabel(t.waba_business_id);
      const metaBits = [t.language || "—", t.category || "—", phones ? `On ${phones}` : ""].filter(Boolean);

      const card = el(`article.tmc-card${statusTone ? `.tmc-card--${statusTone}` : ""}`, {}, [
        el("header.tmc-card__head", {}, [
          el("div", {}, [
            el("h3.tmc-card__name", {}, [t.name]),
            el("p.tmc-card__meta", {}, [metaBits.join(" · ")]),
          ]),
          el("span.tmc-badge", { class: statusTone ? `tmc-badge--${statusTone}` : "" }, [statusLabel]),
        ]),
        el("p.tmc-card__body", {}, [t.body_text || "—"]),
        t.footer_text ? el("p.tmc-card__footer-text", {}, [t.footer_text]) : null,
        el("div.tmc-card__foot", {}, [
          isAdmin
            ? el("button.btn.btn--ghost.btn--sm", {
                type: "button",
                title: "Copy this template to Official numbers that do not have it yet",
                onclick: () => deployMissing(t),
              }, [icon("plus", { size: 14 }), " Copy to missing numbers"])
            : null,
          el("button.btn.btn--ghost.btn--sm", {
            type: "button",
            title: "Hide this template from the panel",
            onclick: () => askRemove(t),
          }, [icon("trash", { size: 14 }), " Hide from panel"]),
          isAdmin
            ? el("button.btn.btn--ghost.btn--sm", {
                type: "button",
                title: "Delete this template name on Meta so it can be recreated",
                onclick: () => askPurgeMeta(t),
              }, [icon("trash", { size: 14 }), " Delete from Meta"])
            : null,
          isApproved
            ? el("button.btn.btn--primary.btn--sm", {
                type: "button",
                onclick: () => {
                  dialog.close();
                  onUseTemplate?.(t);
                },
              }, ["Use in chat"])
            : el("span.tmc-hint", {}, [
                isPending
                  ? "Meta is reviewing this template (1–2 minutes)"
                  : "Not available to send",
              ]),
        ]),
      ]);

      listContainer.append(card);
    }
  }

  function deployMissing(t) {
    if (!window.confirm(`Copy "${t.name}" to every Official number that does not have it yet?`)) return;
    clear(notice).append("Submitting to Meta on missing numbers…");
    notice.className = "tmc-notice";
    notice.hidden = false;
    catalog
      .deployTemplate(t.id, { all_numbers: true })
      .then(async (summary) => {
        await fetchTemplates();
        clear(notice).append(
          `Copied to ${summary.created || 0} business account${summary.created === 1 ? "" : "s"}` +
            (summary.skipped ? ` · ${summary.skipped} skipped` : "") +
            (summary.failed ? ` · ${summary.failed} failed` : "") +
            "."
        );
        notice.className = "tmc-notice tmc-notice--ok";
        notice.hidden = false;
      })
      .catch((err) => {
        clear(notice).append(err.message || "Could not copy this template.");
        notice.className = "tmc-notice tmc-notice--bad";
        notice.hidden = false;
      });
  }

  function askRemove(t) {
    const errorEl = el("p.tmc-notice.tmc-notice--bad", { hidden: true });
    const confirmBtn = el("button.btn.btn--primary.btn--sm", { type: "button" }, [
      icon("trash", { size: 14 }),
      " Hide from panel",
    ]);
    const cancelBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["Cancel"]);
    const confirm = modal("Hide template", el("div.modal__body", {}, [
      el("p", {}, [
        `Hide ${t.name} from this panel? It stays at Meta, but agents will not see it here. Sync will not bring it back.`,
      ]),
      errorEl,
      el("div.tmc-card__foot", {}, [cancelBtn, confirmBtn]),
    ]));
    cancelBtn.addEventListener("click", () => confirm.close());
    confirmBtn.addEventListener("click", async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Removing…";
      errorEl.hidden = true;
      try {
        await catalog.deleteTemplate(t.id);
        confirm.close();
        await fetchTemplates();
        clear(notice).append(`Hidden ${t.name} from the panel.`);
        notice.className = "tmc-notice tmc-notice--ok";
        notice.hidden = false;
      } catch (err) {
        confirmBtn.disabled = false;
        confirmBtn.replaceChildren(icon("trash", { size: 14 }), " Hide from panel");
        errorEl.textContent = err.message || "Could not hide this template.";
        errorEl.hidden = false;
      }
    });
  }

  function askPurgeMeta(t) {
    const errorEl = el("p.tmc-notice.tmc-notice--bad", { hidden: true });
    const confirmBtn = el("button.btn.btn--primary.btn--sm", { type: "button" }, [
      icon("trash", { size: 14 }),
      " Delete from Meta",
    ]);
    const cancelBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["Cancel"]);
    const confirm = modal("Delete from Meta", el("div.modal__body", {}, [
      el("p", {}, [
        `Delete ${t.name} from Meta? The name becomes free to recreate. It is also hidden from this panel so Sync cannot bring it back.`,
      ]),
      errorEl,
      el("div.tmc-card__foot", {}, [cancelBtn, confirmBtn]),
    ]));
    cancelBtn.addEventListener("click", () => confirm.close());
    confirmBtn.addEventListener("click", async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Deleting…";
      errorEl.hidden = true;
      try {
        await catalog.purgeTemplateMeta(t.id);
        confirm.close();
        await fetchTemplates();
        clear(notice).append(`Deleted ${t.name} from Meta and hid it from the panel.`);
        notice.className = "tmc-notice tmc-notice--ok";
        notice.hidden = false;
      } catch (err) {
        confirmBtn.disabled = false;
        confirmBtn.replaceChildren(icon("trash", { size: 14 }), " Delete from Meta");
        errorEl.textContent = err.message || "Could not delete this template on Meta.";
        errorEl.hidden = false;
      }
    });
  }

  fetchTemplates();
  return dialog;
}

/**
 * Every number that shares one business account.
 *
 * A template belongs to a WABA, not to a number, and several of this company's
 * numbers sit on the same one. Saying "created on +9715…" alone would be a
 * half-truth — the template becomes available on all of them — so the screen
 * names them all.
 */
const numbersOnWaba = (numbers, wabaId) =>
  numbers.filter((n) => n.waba_business_id && n.waba_business_id === wabaId);

/** Phone first — titles are often agent names and confuse the picker. */
function formatWaNumber(number) {
  const raw = String(number?.phone_number || "").replace(/\s+/g, "");
  const phone = raw
    ? raw.startsWith("+")
      ? raw
      : `+${raw.replace(/^\+/, "")}`
    : "";
  const name = String(number?.label || number?.title || "").trim();
  const nameIsPhone = name && phone && name.replace(/\s+/g, "").replace(/^\+/, "") === phone.replace(/^\+/, "");
  return {
    phone: phone || (nameIsPhone ? name : "") || `#${number?.id || "?"}`,
    name: name && !nameIsPhone && name !== phone ? name : "",
  };
}

export function openCreateTemplateModal({ onCreated, numbers = null, isAdmin = false } = {}) {
  ensureTemplateCenterCss();

  // Which business account this is being written into. Meta reviews it under
  // that account's name, so it is not a detail to leave implicit — and an agent
  // covering four numbers has no other way to know which one they are spending.
  const numberSelect = el("select.field");
  const wabaNote = el("div.tplc-waba-note", {}, ["Loading numbers…"]);
  const deployAllInput = el("input", { type: "checkbox", checked: true, id: "tplc-deploy-all" });
  // Closed by default. A hundred rows of checkboxes pushed Name, Body and the
  // Submit button off the screen; one line saying how many are selected is
  // what an admin needs, and the list opens only for someone changing it.
  const deployList = el("div.tplc-deploy-list", { hidden: true });
  const deployCount = el("span.tplc-deploy-toggle__count", {}, ["Loading numbers…"]);
  const deployHint = el("span.tplc-deploy-toggle__hint");
  const deployToggle = el(
    "button.tplc-deploy-toggle",
    { type: "button", "aria-expanded": "false", title: "Show or hide the list of numbers" },
    [deployCount, deployHint]
  );
  const chevron = () => svg(["M6 9l6 6 6-6"], { size: 14 });
  clear(deployHint).append("Choose numbers", chevron());
  deployToggle.addEventListener("click", () => {
    deployList.hidden = !deployList.hidden;
    deployToggle.setAttribute("aria-expanded", String(!deployList.hidden));
    clear(deployHint).append(deployList.hidden ? "Choose numbers" : "Done", chevron());
  });
  let allNumbers = Array.isArray(numbers) ? numbers : [];

  function syncDeployAllFromRows() {
    const boxes = [...deployList.querySelectorAll('input[type="checkbox"]')];
    const picked = boxes.filter((box) => box.checked).length;
    deployAllInput.checked = boxes.length > 0 && picked === boxes.length;
    deployCount.textContent = !boxes.length
      ? "No numbers available"
      : picked === boxes.length
        ? `All ${boxes.length} numbers selected`
        : picked === 0
          ? `None of ${boxes.length} numbers selected`
          : `${picked} of ${boxes.length} numbers selected`;
  }

  function paintDeployTargets() {
    clear(deployList);
    for (const number of allNumbers) {
      const { phone, name } = formatWaNumber(number);
      const box = el("input", {
        type: "checkbox",
        checked: true,
        "data-number-id": String(number.id),
      });
      box.addEventListener("change", syncDeployAllFromRows);
      deployList.append(
        el("label.tplc-deploy-row", {}, [
          box,
          el("span.tplc-deploy-row__text", {}, [
            el("span.tplc-deploy-row__phone", {}, [phone]),
            name ? el("span.tplc-deploy-row__name", {}, [name]) : null,
          ]),
        ])
      );
    }
    syncDeployAllFromRows();
  }

  deployAllInput.addEventListener("change", () => {
    for (const box of deployList.querySelectorAll('input[type="checkbox"]')) {
      box.checked = deployAllInput.checked;
    }
    syncDeployAllFromRows();
  });

  function paintNumbers() {
    clear(numberSelect);
    // One option per business account, not per number: two numbers on the same
    // WABA are the same choice, and offering it twice invites the agent to
    // wonder which of the two they picked.
    const seen = new Set();
    for (const number of allNumbers) {
      if (!number.waba_business_id || seen.has(number.waba_business_id)) continue;
      seen.add(number.waba_business_id);
      const shared = numbersOnWaba(allNumbers, number.waba_business_id);
      const phones = shared.map((n) => formatWaNumber(n).phone).join(", ");
      numberSelect.append(
        el("option", { value: number.waba_business_id }, [phones || number.waba_business_id])
      );
    }
    if (!seen.size) {
      numberSelect.append(el("option", { value: "" }, ["No number available"]));
    }
    paintWabaNote();
    if (isAdmin) paintDeployTargets();
  }

  function paintWabaNote() {
    const shared = numbersOnWaba(allNumbers, numberSelect.value);
    clear(wabaNote).append(
      shared.length
        ? shared.map((n) => formatWaNumber(n).phone).join(", ")
        : "Pick a business account."
    );
  }

  numberSelect.addEventListener("change", paintWabaNote);

  if (!allNumbers.length) {
    catalog
      .numbers()
      .then((rows) => {
        allNumbers = Array.isArray(rows) ? rows : [];
        paintNumbers();
      })
      .catch(() => clear(wabaNote).append("Could not load numbers."));
  } else {
    paintNumbers();
  }

  const targetField = isAdmin
    ? el("div.tplc-field", {}, [
        el("div.tplc-field__head", {}, [
          el("span", {}, ["Numbers"]),
          el("label.tplc-deploy-all", {}, [deployAllInput, " Select all"]),
        ]),
        deployToggle,
        deployList,
      ])
    : el("label.tplc-field", {}, [el("span", {}, ["Number"]), numberSelect, wabaNote]);

  const nameInput = el("input.field", {
    type: "text",
    placeholder: "property_viewing_offer",
  });

  const categorySelect = el("select.field", {}, [
    el("option", { value: "MARKETING" }, ["Marketing"]),
    el("option", { value: "UTILITY" }, ["Utility"]),
  ]);

  const langSelect = el("select.field", {}, [
    el("option", { value: "en" }, ["English"]),
    el("option", { value: "ar" }, ["Arabic"]),
    el("option", { value: "ur" }, ["Urdu"]),
  ]);

  /* --------------------------------------------------------------- header */

  // Text is typed here. An image, video or document is a sample file that
  // Meta reviews the template against — the agent attaches the real one each
  // time they send. Text is the default so an empty box still means no header.
  const headerKind = el("select.field.tplc-header__kind", { "aria-label": "Header type" }, [
    el("option", { value: "TEXT" }, ["Text"]),
    el("option", { value: "IMAGE" }, ["Image"]),
    el("option", { value: "VIDEO" }, ["Video"]),
    el("option", { value: "DOCUMENT" }, ["Document (PDF)"]),
  ]);
  const headerInput = el("input.field", { type: "text", placeholder: "Header text (optional)" });
  const headerSample = { handle: "", format: "", name: "", size: 0, previewUrl: "", uploading: false };
  const headerFile = el("input", { type: "file", hidden: true });
  const headerPick = el(
    "button.btn.btn--ghost.btn--sm",
    {
      type: "button",
      onclick: () => {
        // A silently disabled button read as "broken". Say why — right here
        // beside the button, not in the error line below the fold.
        if (headerMediaConfigured === false) {
          headerStatus.classList.add("is-bad");
          headerStatus.textContent =
            "Cannot upload yet: this server has no way to send Meta a sample file (see the note below).";
          headerCapNote.scrollIntoView({ block: "nearest" });
          return;
        }
        errorEl.hidden = true;
        headerFile.click();
      },
    },
    [icon("paperclip", { size: 14 }), " Choose file"]
  );
  const headerStatus = el("span.tplc-media__status", {}, ["No file chosen yet"]);
  const headerMediaRow = el("div.tplc-media__row", { hidden: true }, [headerPick, headerStatus, headerFile]);
  const headerHint = el("span.tplc-field__hint", { hidden: true });
  const headerCapNote = el("div.tplc-note.tplc-note--warn", { hidden: true });
  // Unknown until the server answers; null keeps the button usable meanwhile.
  let headerMediaConfigured = null;

  const SAMPLE_ACCEPT = { IMAGE: "image/jpeg,image/png", VIDEO: "video/mp4", DOCUMENT: "application/pdf,.pdf" };
  const SAMPLE_WORDS = { IMAGE: "JPEG or PNG up to 5 MB", VIDEO: "MP4 up to 16 MB", DOCUMENT: "PDF up to 100 MB" };

  const isMediaHeader = () => Boolean(MEDIA_HEADERS[headerKind.value]);

  function resetHeaderSample() {
    if (headerSample.previewUrl) URL.revokeObjectURL(headerSample.previewUrl);
    Object.assign(headerSample, { handle: "", format: "", name: "", size: 0, previewUrl: "", uploading: false });
  }

  function paintHeaderKind() {
    const kind = headerKind.value;
    const media = isMediaHeader();
    headerInput.hidden = media;
    headerMediaRow.hidden = !media;
    headerHint.hidden = !media;
    headerCapNote.hidden = !(media && headerMediaConfigured === false);
    if (media) {
      // A sample uploaded as an image is not a sample for a video.
      if (headerSample.format && headerSample.format !== kind) resetHeaderSample();
      headerFile.accept = SAMPLE_ACCEPT[kind];
      headerHint.textContent = `${SAMPLE_WORDS[kind]}. Meta reviews this sample; agents attach the real ${MEDIA_HEADERS[kind]} each time they send.`;
      headerPick.classList.toggle("is-off", headerMediaConfigured === false);
      headerPick.title = headerMediaConfigured === false ? "Not available until the server can send Meta a sample file" : "";
      if (!headerSample.uploading) {
        headerStatus.classList.remove("is-bad");
        headerStatus.textContent = headerSample.handle
          ? `${headerSample.name} · ${formatBytes(headerSample.size)} · uploaded`
          : "No file chosen yet";
      }
    }
    updatePreview();
  }

  headerKind.addEventListener("change", paintHeaderKind);

  headerFile.addEventListener("change", async () => {
    const file = headerFile.files?.[0];
    headerFile.value = "";
    if (!file) return;
    const kind = headerKind.value;

    resetHeaderSample();
    headerSample.uploading = true;
    headerSample.format = kind;
    headerStatus.classList.remove("is-bad");
    headerStatus.textContent = `Uploading ${file.name}…`;
    errorEl.hidden = true;
    updatePreview();

    try {
      // The business account the sample is filed under: the first ticked
      // number's, or the picked one. The handle itself is account-agnostic.
      const firstTicked = isAdmin
        ? deployList.querySelector('input[type="checkbox"]:checked')?.dataset.numberId
        : null;
      const firstNumber = firstTicked ? allNumbers.find((n) => String(n.id) === String(firstTicked)) : null;
      const wabaId = isAdmin ? firstNumber?.waba_business_id || "" : numberSelect.value;
      const result = await catalog.uploadTemplateHeaderMedia(file, kind, {
        wabaId,
        onProgress: (ratio) => {
          headerStatus.textContent = `Uploading ${file.name}… ${Math.round(ratio * 100)}%`;
        },
      }).promise;
      Object.assign(headerSample, {
        handle: result.header_handle || "",
        // Who minted it decides which route submits the template later.
        via: result.via || "alots",
        name: file.name,
        size: file.size,
        // Drawn from the local file, so the preview is the actual picture.
        previewUrl: kind === "IMAGE" ? URL.createObjectURL(file) : "",
      });
      headerStatus.textContent = `${file.name} · ${formatBytes(file.size)} · uploaded`;
    } catch (err) {
      headerSample.format = "";
      headerStatus.classList.add("is-bad");
      headerStatus.textContent = err.message || "Upload failed.";
    } finally {
      headerSample.uploading = false;
      updatePreview();
    }
  });

  // Asked once when the form opens, so a server that cannot take a sample
  // says so beside the picker rather than as the failure of an upload.
  catalog
    .headerMediaStatus()
    .then((answer) => {
      headerMediaConfigured = Boolean(answer?.configured);
      if (!headerMediaConfigured) {
        clear(headerCapNote).append(
          answer?.detail || "Image, video and document headers are not available on this server yet."
        );
      }
      paintHeaderKind();
    })
    .catch(() => {});

  const bodyTextarea = el("textarea.field", {
    rows: 4,
    placeholder: "Hello {{1}}, your appointment is on {{2}}.",
  });
  const footerInput = el("input.field", { type: "text", placeholder: "Footer (optional)" });

  /**
   * A sample value for every {{n}}, which Meta requires and this screen never
   * asked for.
   *
   * The review is a person reading the finished sentence, and "Hello {{1}}" is
   * not one — a template submitted without examples comes back rejected, and
   * the panel reported that as though the wording were at fault. The values are
   * also what the preview draws, so the agent sees the message a customer will
   * get rather than the skeleton of it.
   */
  const headerExamples = {};
  const bodyExamples = {};

  const headerVars = el("div.tplc-vars", { hidden: true });
  const bodyVars = el("div.tplc-vars", { hidden: true });

  function paintVariables(text, store, container, label) {
    const holes = placeholdersIn(text);
    container.hidden = !holes.length;
    // Values for placeholders the agent has since deleted must go too, or a
    // removed {{3}} keeps sending an example for a hole that is not there.
    for (const key of Object.keys(store)) {
      if (!holes.includes(key)) delete store[key];
    }
    if (!holes.length) return;

    clear(container).append(el("div.tplc-vars__title", {}, [`Sample for ${label}`]));
    for (const hole of holes) {
      const input = el("input.field.tplc-vars__input", {
        type: "text",
        value: store[hole] || "",
        placeholder: `{{${hole}}} example`,
      });
      input.addEventListener("input", () => {
        store[hole] = input.value;
        updatePreview();
      });
      container.append(
        el("label.tplc-vars__row", {}, [el("span", {}, [`{{${hole}}}`]), input])
      );
    }
  }

  const addVariable = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["+ Add a variable"]);
  addVariable.addEventListener("click", () => {
    // The next number, not always {{1}} — appending a duplicate is the one
    // thing Meta will not accept and the old two fixed buttons made it easy.
    const next = placeholdersIn(bodyTextarea.value).length + 1;
    bodyTextarea.value = `${bodyTextarea.value.trimEnd()} {{${next}}}`.trim();
    bodyTextarea.focus();
    updatePreview();
  });

  /* ------------------------------------------------------------- buttons */

  const buttons = [];
  const buttonRows = el("div.tplc-btnedit");
  const addButton = el("button.btn.btn--ghost.btn--sm", { type: "button" }, ["+ Add a button"]);

  function paintButtons() {
    clear(buttonRows);
    addButton.disabled = buttons.length >= MAX_VISIBLE_BUTTONS;

    buttons.forEach((button, index) => {
      const kind = el("select.field.tplc-btnedit__kind", {}, [
        el("option", { value: "QUICK_REPLY" }, ["Quick reply"]),
        el("option", { value: "URL" }, ["Open a link"]),
        el("option", { value: "PHONE_NUMBER" }, ["Call a number"]),
      ]);
      kind.value = button.type;

      const text = el("input.field", {
        type: "text",
        value: button.text || "",
        maxlength: "25",
        placeholder: "Button label, max 25 characters",
      });

      // Only one of these is ever shown — a quick reply carries nothing but its
      // own label, and asking for a URL beside it invites one to be typed and
      // silently dropped.
      const extra = el("input.field", {
        type: "text",
        value: button.type === "URL" ? button.url || "" : button.phone_number || "",
        placeholder:
          button.type === "URL"
            ? "https://a7groupdxb.com/listing/{{1}}"
            : "+9715XXXXXXXX",
        hidden: button.type === "QUICK_REPLY",
      });

      // A link ending in a placeholder is how one template points each customer
      // at their own page, and Meta wants the finished link as proof.
      const sample = el("input.field", {
        type: "text",
        value: button.example || "",
        placeholder: "What that link looks like filled in",
        hidden: !(button.type === "URL" && placeholdersIn(button.url).length),
      });

      const remove = el("button.btn.btn--ghost.btn--sm", { type: "button", title: "Remove this button" }, [icon("close", { size: 14 })]);

      kind.addEventListener("change", () => {
        button.type = kind.value;
        paintButtons();
        updatePreview();
      });
      text.addEventListener("input", () => {
        button.text = text.value;
        updatePreview();
      });
      extra.addEventListener("input", () => {
        if (button.type === "URL") button.url = extra.value;
        else button.phone_number = extra.value;
        sample.hidden = !(button.type === "URL" && placeholdersIn(extra.value).length);
        updatePreview();
      });
      sample.addEventListener("input", () => {
        button.example = sample.value;
      });
      remove.addEventListener("click", () => {
        buttons.splice(index, 1);
        paintButtons();
        updatePreview();
      });

      buttonRows.append(
        el("div.tplc-btnedit__row", {}, [
          el("div.tplc-btnedit__top", {}, [kind, text, remove]),
          extra,
          sample,
        ])
      );
    });
  }

  addButton.addEventListener("click", () => {
    if (buttons.length >= MAX_VISIBLE_BUTTONS) return;
    buttons.push({ type: "QUICK_REPLY", text: "", url: "", phone_number: "", example: "" });
    paintButtons();
    updatePreview();
  });

  const nameHint = el("span.tplc-field__hint", {}, ["lowercase_with_underscores"]);

  nameInput.addEventListener("input", () => {
    nameInput.value = nameInput.value.toLowerCase().replace(/[^\w]+/g, "_");
    nameHint.textContent = nameInput.value || "lowercase_with_underscores";
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

  function sampleBubble(kind) {
    if (kind === "IMAGE" && headerSample.previewUrl) {
      return el("img.tplc-bubble__image", { src: headerSample.previewUrl, alt: "" });
    }
    const label = headerSample.handle
      ? `${headerSample.name} · ${formatBytes(headerSample.size)}`
      : headerSample.uploading
        ? "Uploading…"
        : `${MEDIA_HEADERS[kind]} header — no file chosen yet`;
    return el("div.tplc-bubble__media", { class: headerSample.handle ? "" : "is-missing" }, [
      mediaGlyph(kind),
      el("span", {}, [label]),
    ]);
  }

  function updatePreview() {
    const media = isMediaHeader();
    paintVariables(media ? "" : headerInput.value, headerExamples, headerVars, "header");
    paintVariables(bodyTextarea.value, bodyExamples, bodyVars, "body");

    clear(previewBody);
    if (media) {
      previewBody.append(sampleBubble(headerKind.value));
    } else if (headerInput.value.trim()) {
      previewBody.append(
        el("div.tplc-bubble__header", {}, [withValues(headerInput.value.trim(), headerExamples)])
      );
    }

    // withValues, not the raw text: the placeholders are drawn with the sample
    // values in them, so what is on screen is a message rather than a form. An
    // unfilled hole stays visible and tinted, which is the thing still to do.
    const bodyText = bodyTextarea.value.trim();
    previewBody.append(
      el("div.tplc-bubble__body", {}, [
        bodyText
          ? withValues(bodyText, bodyExamples)
          : "Your template message body text will appear here…",
      ])
    );

    if (footerInput.value.trim()) {
      previewBody.append(el("div.tplc-bubble__footer", {}, [footerInput.value.trim()]));
    }

    const drawable = buttons.filter((b) => (b.text || "").trim());
    if (drawable.length) {
      previewBody.append(
        el(
          "div.tplc-btns",
          {},
          drawable.map((b) =>
            el("span.tplc-btn", {}, [buttonIcon(b.type), b.text.trim()])
          )
        )
      );
    }
  }

  const aiNote = el("p.tplc-ai__note", { hidden: true });
  const aiList = el("div.tplc-ai__list");
  const aiSource = el("p.tplc-ai__note", { hidden: true });
  const aiPanel = el("div.tplc-ai", { hidden: true }, [aiNote, aiList, aiSource]);
  const aiBtn = el("button.btn.btn--ghost.btn--sm", { type: "button" }, [
    icon("zap", { size: 14 }),
    " Rewrite as Utility",
  ]);

  let aiPickedName = "";

  function fillExampleStore(store, incoming) {
    for (const key of Object.keys(store)) delete store[key];
    for (const [key, value] of Object.entries(incoming || {})) {
      store[String(key)] = String(value || "");
    }
  }

  function applyUtilitySuggestion(row) {
    aiPickedName = row.name;
    nameInput.value = row.name;
    nameHint.textContent = row.name || "lowercase_with_underscores";
    categorySelect.value = "UTILITY";
    // A suggested wording comes with text or with no header; a sample file
    // the agent already uploaded is kept unless the suggestion has text.
    if (row.header) {
      headerKind.value = "TEXT";
      headerInput.value = row.header;
    } else if (headerKind.value === "TEXT") {
      headerInput.value = "";
    }
    paintHeaderKind();
    bodyTextarea.value = row.body || "";
    footerInput.value = row.footer || "";
    fillExampleStore(headerExamples, row.header_examples);
    fillExampleStore(bodyExamples, row.body_examples);
    buttons.splice(0, buttons.length, ...(Array.isArray(row.buttons) ? row.buttons.map((b) => ({
      type: "QUICK_REPLY",
      text: b.text || "",
      url: "",
      phone_number: "",
      example: "",
    })) : []));
    paintButtons();
    updatePreview();
    for (const card of aiList.querySelectorAll(".tplc-ai__card")) {
      card.classList.toggle("is-picked", card.dataset.name === row.name);
    }
  }

  function paintUtilitySuggestions(payload) {
    clear(aiList);
    const rows = Array.isArray(payload?.suggestions) ? payload.suggestions.slice(0, 3) : [];
    const marketing = Boolean(payload?.original_would_be_marketing);
    const fromAi = payload?.source === "openai" && payload?.ai_configured === true;
    clear(aiNote).append(
      payload?.analysis
        || (marketing
          ? "This draft would be approved as Marketing. Pick a Utility wording below."
          : "Pick one Utility wording. Meta scores the text, not the category dropdown.")
    );
    aiNote.className = marketing ? "tplc-ai__note" : "tplc-ai__note tplc-ai__note--ok";
    aiNote.hidden = false;

    clear(aiSource);
    if (fromAi) {
      aiSource.hidden = true;
    } else {
      const err = String(payload?.ai_error || "").trim();
      aiSource.append(
        err || "Rewrite service is not configured",
        " These wordings are from your draft."
      );
      aiSource.className = "tplc-ai__note";
      aiSource.hidden = false;
    }

    if (!rows.length) {
      aiList.append(el("p.tplc-ai__note.tplc-ai__note--bad", {}, ["No Utility rewrites came back. Try again."]));
      return;
    }

    for (const row of rows) {
      const useBtn = el("button.btn.btn--primary.btn--sm", { type: "button" }, ["Use this"]);
      useBtn.addEventListener("click", () => applyUtilitySuggestion(row));
      aiList.append(
        el("article.tplc-ai__card", { "data-name": row.name, class: row.name === aiPickedName ? "is-picked" : "" }, [
          el("div.tplc-ai__card-head", {}, [
            el("h3.tplc-ai__name", {}, [row.name || "utility_template"]),
            useBtn,
          ]),
          el("p.tplc-ai__body", {}, [row.body || ""]),
        ])
      );
    }
  }

  aiBtn.addEventListener("click", async () => {
    const bodyText = bodyTextarea.value.trim();
    if (!bodyText) {
      errorEl.textContent = "Write the template body first, then rewrite it as Utility.";
      errorEl.hidden = false;
      return;
    }
    errorEl.hidden = true;
    aiPanel.hidden = false;
    aiBtn.disabled = true;
    aiBtn.replaceChildren("Analysing…");
    clear(aiList).append(el("p.tplc-ai__note", {}, ["Checking whether Meta would treat this as Marketing…"]));
    aiNote.hidden = true;
    aiSource.hidden = true;
    try {
      const payload = await catalog.suggestUtilityTemplates({
        name: nameInput.value.trim(),
        category: categorySelect.value,
        language: langSelect.value,
        header_text: isMediaHeader() ? "" : headerInput.value.trim(),
        body_text: bodyText,
        footer_text: footerInput.value.trim(),
      });
      paintUtilitySuggestions(payload);
    } catch (err) {
      clear(aiNote).append(err.message || "Could not rewrite this as Utility.");
      aiNote.className = "tplc-ai__note tplc-ai__note--bad";
      aiNote.hidden = false;
      aiSource.hidden = true;
      clear(aiList);
    } finally {
      aiBtn.disabled = false;
      aiBtn.replaceChildren(icon("zap", { size: 14 }), " Rewrite as Utility");
    }
  });

  const errorEl = el("div.alert", { hidden: true });
  const submitBtn = el("button.btn.btn--primary", { type: "button" }, [
    icon("send", { size: 14 }),
    " Submit Template to Meta",
  ]);

  const leftForm = el("div.tplc-form", { style: "gap: 10px;" }, [
    targetField,
    el("label.tplc-field", {}, [el("span", {}, ["Name"]), nameInput, nameHint]),
    el("label.tplc-field", {}, [
      el("div.tplc-field__head", {}, [el("span", {}, ["Category"]), aiBtn]),
      categorySelect,
    ]),
    el("label.tplc-field", {}, [el("span", {}, ["Language"]), langSelect]),
    el("div.tplc-field", {}, [
      el("span", {}, ["Header"]),
      el("div.tplc-header", {}, [headerKind, headerInput, headerMediaRow]),
      headerHint,
      headerCapNote,
    ]),
    headerVars,
    el("label.tplc-field", {}, [
      el("div.tplc-field__head", {}, [el("span", {}, ["Body"]), addVariable]),
      bodyTextarea,
    ]),
    bodyVars,
    aiPanel,
    el("label.tplc-field", {}, [el("span", {}, ["Footer"]), footerInput]),
    el("div.tplc-field", {}, [
      el("div.tplc-field__head", {}, [
        el("span", {}, [`Buttons (max ${MAX_VISIBLE_BUTTONS})`]),
        addButton,
      ]),
      buttonRows,
    ]),
    errorEl,
    el("div.tplc-actions", {}, [submitBtn]),
  ]);

  const body = el("div.modal__body.tplc", {}, [leftForm, el("div.tplc-right", {}, [phoneFrame])]);
  const dialog = modal("Create WhatsApp Template", body, { wide: true });

  paintButtons();
  updatePreview();

  /** The first thing wrong with the form, or "" when there is nothing. */
  function whatIsWrong() {
    if (!nameInput.value.trim()) return "Give the template a name.";
    if (!bodyTextarea.value.trim()) return "The template needs body text.";

    // Checked here rather than left to Meta. A rejection is recorded against
    // the business account and cannot be taken back, so the cheap mistakes are
    // worth catching on this side of the submission.
    for (const [hole, value] of Object.entries({ ...headerExamples, ...bodyExamples })) {
      if (!String(value || "").trim()) return `Give {{${hole}}} a sample value — Meta reviews the finished sentence.`;
    }
    const body = bodyTextarea.value.trim();
    const holes = placeholdersIn(body);
    if (holes.length) {
      const expected = holes.map((_, i) => String(i + 1));
      if (holes.join(",") !== expected.join(",")) {
        return "Placeholders must be {{1}}, {{2}}, … in order with no gaps.";
      }
      if (body.startsWith("{{") || /\{\{\d+\}\}$/.test(body)) {
        return "Body cannot start or end with a variable — Meta rejects that. Add words before {{1}} and after the last one.";
      }
    }
    if (isMediaHeader()) {
      if (headerSample.uploading) return "Wait for the header file to finish uploading.";
      if (!headerSample.handle) return `Choose the ${MEDIA_HEADERS[headerKind.value]} for the header.`;
    } else if (headerInput.value.trim().length > 60) {
      return "Header text must be 60 characters or fewer.";
    }
    if (footerInput.value.trim().length > 60) return "Footer text must be 60 characters or fewer.";
    for (const button of buttons) {
      if (!button.text.trim()) return "Every button needs a label, or remove it.";
      if (button.type === "URL" && !button.url.trim()) return `Button "${button.text}" needs a link.`;
      if (button.type === "PHONE_NUMBER" && !button.phone_number.trim()) {
        return `Button "${button.text}" needs a phone number.`;
      }
    }
    if (!isAdmin && !numberSelect.value) return "No WhatsApp number available.";
    if (isAdmin) {
      const picked = deployList.querySelectorAll('input[type="checkbox"]:checked');
      if (!picked.length) return "Select at least one number.";
    }
    return "";
  }

  function templatePayload() {
    return {
      name: nameInput.value.trim(),
      category: categorySelect.value,
      language: langSelect.value,
      header_format: headerKind.value,
      header_text: isMediaHeader() ? "" : headerInput.value.trim(),
      header_examples: headerExamples,
      header_handle: isMediaHeader() ? headerSample.handle : "",
      header_handle_via: isMediaHeader() ? headerSample.via || "alots" : "",
      body_text: bodyTextarea.value.trim(),
      body_examples: bodyExamples,
      footer_text: footerInput.value.trim(),
      buttons: buttons.map((b) => ({
        type: b.type,
        text: b.text.trim(),
        url: b.type === "URL" ? b.url.trim() : "",
        phone_number: b.type === "PHONE_NUMBER" ? b.phone_number.trim() : "",
        example: b.example.trim(),
      })),
    };
  }

  submitBtn.addEventListener("click", async () => {
    const problem = whatIsWrong();
    if (problem) {
      errorEl.textContent = problem;
      errorEl.hidden = false;
      return;
    }

    const numberIds = isAdmin
      ? [...deployList.querySelectorAll('input[type="checkbox"]:checked')].map(
          (node) => node.dataset.numberId
        )
      : [];
    const accountCount = isAdmin ? Math.max(1, numberIds.length) : 1;

    submitBtn.disabled = true;
    submitBtn.textContent =
      accountCount > 1
        ? `Submitting to Meta on ${accountCount} numbers…`
        : "Submitting to Meta…";
    errorEl.hidden = true;

    try {
      const payload = templatePayload();
      let summary = null;
      if (isAdmin) {
        // Always send the checked ids — never all_numbers:true alone. That flag
        // expands to every Official number on the portal and can sit on Meta
        // for minutes while the button still says Submitting.
        summary = await catalog.createTemplateBulk({
          ...payload,
          all_numbers: false,
          number_ids: numberIds,
        });
      } else {
        await catalog.createTemplate({
          ...payload,
          waba_business_id: numberSelect.value,
        });
      }

      dialog.close();
      onCreated?.(summary);
    } catch (err) {
      submitBtn.disabled = false;
      submitBtn.replaceChildren(icon("send", { size: 14 }), " Submit Template to Meta");
      errorEl.textContent = err.message || "Failed to submit template to Meta.";
      errorEl.hidden = false;
    }
  });

  return dialog;
}
