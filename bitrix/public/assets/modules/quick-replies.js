/**
 * Quick Replies Manager & Inline Slash `/` Autocomplete
 */

import { inbox } from "../api/api.js";
import { clear, el, modal, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";

export function openQuickRepliesModal({ isWaAdmin, onSelectReply } = {}) {
  const body = el("div.modal__body.na", {}, [el("div.na-note", {}, ["Loading saved replies…"])]);
  const dialog = modal("Manage Quick Replies", body, { wide: true });

  let replies = [];

  const shortcutInput = el("input.field", { type: "text", placeholder: "e.g. greeting" });
  const bodyTextarea = el("textarea.field", { rows: 3, placeholder: "Type the full quick reply response message..." });
  const sharedCheckbox = el("input", { type: "checkbox" });
  const sharedLabel = isWaAdmin
    ? el("label.akit-check", {}, [
        sharedCheckbox,
        "Share with everyone on the team",
      ])
    : null;

  const errorEl = el("div.alert", { hidden: true });
  const saveBtn = el("button.btn.btn--primary.btn--sm", { type: "button" }, [
    icon("plus", { size: 14 }),
    " Save Quick Reply",
  ]);

  const listContainer = el("div.akit-list");

  shortcutInput.addEventListener("input", () => {
    shortcutInput.value = shortcutInput.value.toLowerCase().replace(/[^\w-]+/g, "");
  });

  async function fetchReplies() {
    try {
      replies = await inbox.quickReplies();
      render();
    } catch (err) {
      clear(body).append(el("div.alert", {}, [`Failed to load quick replies: ${err.message}`]));
    }
  }

  function render() {
    clear(body);
    clear(listContainer);

    const formBlock = el("div.akit-card.tplc-form", {}, [
      el("div.akit-card__title", {}, ["Create New Quick Reply"]),
      el("label.tplc-field", {}, [el("span", {}, ["Shortcut (typed after /)"]), shortcutInput]),
      el("label.tplc-field", {}, [el("span", {}, ["Message Body"]), bodyTextarea]),
      sharedLabel,
      errorEl,
      el("div.tplc-actions", {}, [saveBtn]),
    ]);

    if (!replies.length) {
      listContainer.append(el("div.tplc-empty", {}, ["No saved quick replies yet."]));
    } else {
      for (const reply of replies) {
        const item = el("div.akit-row", {}, [
          el("div.akit-row__main", {}, [
            el("div.akit-row__top", {}, [
              el("span.akit-shortcut", {}, [`/${reply.shortcut}`]),
              reply.is_shared
                ? el("span.na-badge.na-badge--ok", {}, ["Shared"])
                : el("span.na-badge", {}, ["Personal"]),
            ]),
            el("div.akit-body", {}, [reply.body]),
          ]),
          el("div.akit-actions", {}, [
            onSelectReply
              ? el("button.btn.btn--primary.btn--sm", {
                  type: "button",
                  onclick: () => {
                    dialog.close();
                    onSelectReply(reply);
                  },
                }, ["Use"])
              : null,
            el("button.btn.btn--danger.btn--sm", {
              type: "button",
              onclick: async () => {
                try {
                  await inbox.deleteQuickReply(reply.id);
                  await fetchReplies();
                } catch (err) {
                  toast(err.message || "Failed to delete quick reply", "err");
                }
              },
            }, [icon("trash", { size: 14 })]),
          ]),
        ]);
        listContainer.append(item);
      }
    }

    body.append(formBlock, el("h3.akit-section-title", {}, ["Saved Replies"]), listContainer);
  }

  saveBtn.addEventListener("click", async () => {
    const shortcut = shortcutInput.value.trim().replace(/^\//, "");
    const replyBody = bodyTextarea.value.trim();

    if (!shortcut || !replyBody) {
      errorEl.textContent = "Shortcut and message body are required.";
      errorEl.hidden = false;
      return;
    }

    saveBtn.disabled = true;
    errorEl.hidden = true;

    try {
      await inbox.createQuickReply({
        shortcut,
        body: replyBody,
        is_shared: isWaAdmin ? sharedCheckbox.checked : false,
      });
      shortcutInput.value = "";
      bodyTextarea.value = "";
      if (sharedCheckbox) sharedCheckbox.checked = false;
      await fetchReplies();
    } catch (err) {
      errorEl.textContent = err.message || "Failed to save quick reply.";
      errorEl.hidden = false;
    } finally {
      saveBtn.disabled = false;
    }
  });

  fetchReplies();
  return dialog;
}

/**
 * Binds inline `/shortcut` autocomplete popup on composer textarea.
 */
export function bindSlashAutocomplete({ textarea, isWaAdmin, onApply }) {
  const popup = el("div.slash-popup");

  document.body.append(popup);

  let repliesCache = null;
  let activeIndex = 0;

  async function loadCache() {
    try {
      repliesCache = await inbox.quickReplies();
    } catch {
      repliesCache = [];
    }
  }

  function getQuery() {
    const val = textarea.value;
    const pos = textarea.selectionStart;
    const textBefore = val.slice(0, pos);
    const match = textBefore.match(/\/([\w-]*)$/);
    return match ? match[1] : null;
  }

  function closePopup() {
    popup.style.display = "none";
    clear(popup);
  }

  async function renderPopup(query) {
    if (repliesCache === null) await loadCache();
    const matches = (repliesCache || []).filter((r) => r.shortcut.toLowerCase().includes(query.toLowerCase()));

    clear(popup);
    if (!matches.length) {
      closePopup();
      return;
    }

    activeIndex = Math.min(activeIndex, matches.length - 1);

    for (let i = 0; i < matches.length; i++) {
      const r = matches[i];
      const row = el(
        "div.slash-popup__item",
        {
          class: i === activeIndex ? "is-active" : "",
          onmousedown: (e) => {
            e.preventDefault();
            applyReply(r);
          },
        },
        [
          el("div.slash-popup__meta", {}, [
            el("span.akit-shortcut", {}, [`/${r.shortcut}`]),
            el("span.slash-popup__preview", {}, [(r.body || "").slice(0, 30)]),
          ]),
          r.is_shared ? el("span.slash-popup__tag", {}, ["Shared"]) : null,
        ]
      );
      popup.append(row);
    }

    const rect = textarea.getBoundingClientRect();
    popup.style.left = `${Math.max(10, rect.left)}px`;
    popup.style.bottom = `${window.innerHeight - rect.top + 6}px`;
    popup.style.display = "block";
  }

  function applyReply(reply) {
    const val = textarea.value;
    const pos = textarea.selectionStart;
    const textBefore = val.slice(0, pos);
    const textAfter = val.slice(pos);
    const slashIdx = textBefore.lastIndexOf("/");

    if (slashIdx !== -1) {
      textarea.value = textBefore.slice(0, slashIdx) + reply.body + textAfter;
      textarea.selectionStart = textarea.selectionEnd = slashIdx + reply.body.length;
    } else {
      textarea.value = reply.body;
    }

    closePopup();
    onApply?.();
  }

  textarea.addEventListener("input", () => {
    const query = getQuery();
    if (query !== null) {
      renderPopup(query);
    } else {
      closePopup();
    }
  });

  textarea.addEventListener("keydown", (e) => {
    if (popup.style.display === "block") {
      if (e.key === "Escape") {
        e.preventDefault();
        closePopup();
      } else if (e.key === "Enter" || e.key === "Tab") {
        const query = getQuery();
        if (query !== null) {
          const matches = (repliesCache || []).filter((r) => r.shortcut.toLowerCase().includes(query.toLowerCase()));
          if (matches[activeIndex]) {
            e.preventDefault();
            applyReply(matches[activeIndex]);
          }
        }
      }
    }
  });

  textarea.addEventListener("blur", () => {
    setTimeout(closePopup, 200);
  });
}
