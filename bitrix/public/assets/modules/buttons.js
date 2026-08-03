/**
 * KAAM C — REPLY BUTTONS (buttons.js)
 * Modal form & live preview for sending 1-3 interactive reply buttons.
 * Enforces character limits, live counters, error handling without losing agent's input.
 */

import { el, clear, modal } from "../core/dom.js";
import { sendReplyButtons } from "../api/api-extras.js";

function getActiveConversationId() {
  return (
    window.a7wa?.activeConversationId ||
    window.a7wa?.getActiveConversationId?.() ||
    document.querySelector(".thread__composer")?.dataset?.conversationId ||
    document.querySelector("#wa-composer-slot")?.dataset?.conversationId ||
    null
  );
}

function slugify(text) {
  return (
    String(text || "")
      .toLowerCase()
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/[\s_-]+/g, "_")
      .replace(/^_+|_+$/g, "") || "btn"
  );
}

export function mountButtons() {
  const slot = document.querySelector("#wa-composer-slot");
  if (!slot) {
    console.warn("[buttons.js] #wa-composer-slot anchor missing — reply buttons icon skipped");
    return;
  }

  // Interactive buttons icon
  const iconSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  iconSvg.setAttribute("viewBox", "0 0 24 24");
  iconSvg.setAttribute("width", "18");
  iconSvg.setAttribute("height", "18");
  iconSvg.setAttribute("fill", "none");
  iconSvg.setAttribute("stroke", "currentColor");
  iconSvg.setAttribute("stroke-width", "2");
  iconSvg.setAttribute("stroke-linecap", "round");
  iconSvg.setAttribute("stroke-linejoin", "round");
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("x", "3");
  rect.setAttribute("y", "3");
  rect.setAttribute("width", "18");
  rect.setAttribute("height", "18");
  rect.setAttribute("rx", "2");
  const line1 = document.createElementNS("http://www.w3.org/2000/svg", "path");
  line1.setAttribute("d", "M8 9h8M8 13h8M8 17h5");
  iconSvg.appendChild(rect);
  iconSvg.appendChild(line1);

  const btnIcon = el("button.wa-x-btn-icon", { type: "button", title: "Send reply buttons" }, [iconSvg]);

  slot.append(btnIcon);

  btnIcon.addEventListener("click", () => {
    const convId = getActiveConversationId();
    if (!convId) {
      alert("Select a chat first.");
      return;
    }
    openButtonsModal(convId);
  });
}

function openButtonsModal(conversationId) {
  let buttonTitles = ["Yes", "No"]; // default 2 buttons

  // Form elements
  const headerInput = el("input.wa-x-field", { type: "text", maxlength: "60", placeholder: "Damac Hills 2 (optional)" });
  const headerCounter = el("span.wa-x-char-counter", {}, ["0/60"]);

  const bodyTextarea = el("textarea.wa-x-field.wa-x-textarea", {
    rows: 3,
    maxlength: "1024",
    placeholder: "Would you like to arrange a site visit?",
  });
  const bodyCounter = el("span.wa-x-char-counter", {}, ["0/1024"]);

  const footerInput = el("input.wa-x-field", { type: "text", maxlength: "60", placeholder: "A7 Group (optional)" });
  const footerCounter = el("span.wa-x-char-counter", {}, ["0/60"]);

  const buttonsContainer = el("div.wa-x-buttons-form-list");
  const addBtn = el("button.wa-x-btn.wa-x-btn--sm.wa-x-btn--ghost", { type: "button" }, ["+ Button"]);

  const errorEl = el("div.wa-x-alert", { hidden: true });
  const sendBtn = el("button.wa-x-btn.wa-x-btn--primary", { type: "button" }, ["Send buttons"]);

  // Live preview elements
  const previewHeader = el("div.wa-x-preview-header");
  const previewBody = el("div.wa-x-preview-body");
  const previewFooter = el("div.wa-x-preview-footer");
  const previewButtonsList = el("div.wa-x-preview-buttons-list");

  const previewBubble = el("div.wa-x-preview-bubble", {}, [
    previewHeader,
    previewBody,
    previewFooter,
    previewButtonsList,
  ]);

  const updatePreview = () => {
    // Header
    const hText = headerInput.value.trim();
    previewHeader.textContent = hText;
    previewHeader.hidden = !hText;

    // Body
    const bText = bodyTextarea.value.trim();
    previewBody.textContent = bText || "Message text…";

    // Footer
    const fText = footerInput.value.trim();
    previewFooter.textContent = fText;
    previewFooter.hidden = !fText;

    // Buttons preview
    clear(previewButtonsList);
    buttonTitles.forEach((t) => {
      previewButtonsList.append(el("div.wa-x-preview-btn-item", {}, [t || "Button"]));
    });

    // Counters
    headerCounter.textContent = `${headerInput.value.length}/60`;
    bodyCounter.textContent = `${bodyTextarea.value.length}/1024`;
    footerCounter.textContent = `${footerInput.value.length}/60`;
  };

  const renderButtonsForm = () => {
    clear(buttonsContainer);

    buttonTitles.forEach((title, index) => {
      const input = el("input.wa-x-field", {
        type: "text",
        maxlength: "20",
        value: title,
        placeholder: `Button ${index + 1} title`,
        oninput: (e) => {
          buttonTitles[index] = e.target.value;
          updatePreview();
        },
      });

      const counter = el("span.wa-x-char-counter", {}, [`${title.length}/20`]);

      input.addEventListener("input", (e) => {
        counter.textContent = `${e.target.value.length}/20`;
      });

      const delBtn = el(
        "button.wa-x-action-btn.wa-x-action-btn--del",
        {
          type: "button",
          disabled: buttonTitles.length <= 1,
          onclick: () => {
            if (buttonTitles.length > 1) {
              buttonTitles.splice(index, 1);
              renderButtonsForm();
              updatePreview();
            }
          },
        },
        ["×"]
      );

      const row = el("div.wa-x-button-input-row", {}, [
        el("div.wa-x-field-with-counter", {}, [input, counter]),
        delBtn,
      ]);

      buttonsContainer.append(row);
    });

    addBtn.disabled = buttonTitles.length >= 3;
    updatePreview();
  };

  addBtn.addEventListener("click", () => {
    if (buttonTitles.length < 3) {
      buttonTitles.push(`Option ${buttonTitles.length + 1}`);
      renderButtonsForm();
    }
  });

  headerInput.addEventListener("input", updatePreview);
  bodyTextarea.addEventListener("input", updatePreview);
  footerInput.addEventListener("input", updatePreview);

  renderButtonsForm();

  const formSection = el("div.wa-x-buttons-form", {}, [
    el("label.wa-x-field-row", {}, [
      el("div.wa-x-label-head", {}, [el("span", {}, ["Header (optional)"]), headerCounter]),
      headerInput,
    ]),
    el("label.wa-x-field-row", {}, [
      el("div.wa-x-label-head", {}, [el("span", {}, ["Message Body (required)"]), bodyCounter]),
      bodyTextarea,
    ]),
    el("label.wa-x-field-row", {}, [
      el("div.wa-x-label-head", {}, [el("span", {}, ["Footer (optional)"]), footerCounter]),
      footerInput,
    ]),
    el("div.wa-x-field-row", {}, [
      el("div.wa-x-label-head", {}, [el("span", {}, ["Reply Buttons (1–3, max 20 chars each)"])]),
      buttonsContainer,
      el("div.wa-x-add-btn-wrapper", {}, [addBtn]),
    ]),
    errorEl,
    el("div.wa-x-modal-actions", {}, [sendBtn]),
  ]);

  const previewSection = el("div.wa-x-buttons-preview-pane", {}, [
    el("div.wa-x-preview-title", {}, ["WhatsApp Live Preview"]),
    previewBubble,
  ]);

  const modalBody = el("div.wa-x-buttons-split", {}, [formSection, previewSection]);

  const dlg = modal("Send reply buttons", modalBody, { wide: true });

  sendBtn.addEventListener("click", async () => {
    errorEl.hidden = true;

    const bodyVal = bodyTextarea.value.trim();
    if (!bodyVal) {
      errorEl.textContent = "The message body is required.";
      errorEl.hidden = false;
      return;
    }

    if (buttonTitles.length < 1 || buttonTitles.length > 3) {
      errorEl.textContent = "Between one and three buttons are allowed.";
      errorEl.hidden = false;
      return;
    }

    const formattedButtons = [];
    const usedIds = new Set();

    for (let i = 0; i < buttonTitles.length; i++) {
      const title = buttonTitles[i].trim();
      if (!title) {
        errorEl.textContent = `Button ${i + 1} needs a title.`;
        errorEl.hidden = false;
        return;
      }
      if (title.length > 20) {
        errorEl.textContent = `"${title}" is longer than 20 characters.`;
        errorEl.hidden = false;
        return;
      }

      let btnId = slugify(title);
      if (usedIds.has(btnId)) {
        btnId = `${btnId}_${i + 1}`;
      }
      usedIds.add(btnId);

      formattedButtons.push({
        id: btnId,
        title: title,
      });
    }

    sendBtn.disabled = true;
    sendBtn.textContent = "Sending…";

    try {
      await sendReplyButtons(conversationId, {
        body: bodyVal,
        buttons: formattedButtons,
        header: headerInput.value.trim() || undefined,
        footer: footerInput.value.trim() || undefined,
      });

      dlg.close();
    } catch (err) {
      sendBtn.disabled = false;
      sendBtn.textContent = "Send buttons";
      errorEl.textContent = err.message || "The reply buttons could not be sent.";
      errorEl.hidden = false;
      // Note: Modal stays OPEN so user input is NOT lost!
    }
  });
}
