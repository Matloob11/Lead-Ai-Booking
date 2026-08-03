/**
 * Forward Message Modal: Search conversations & forward message.
 */

import { inbox } from "../api/api.js";
import { clear, el, modal } from "../core/dom.js";
import { icon } from "../core/icons.js";

export function openForwardModal({ message, conversations = [], onForward }) {
  const searchInput = el("input.field", {
    type: "text",
    placeholder: "Search contact or phone number…",
  });

  const listContainer = el("div.na-rows", { style: "max-height: 280px; overflow-y: auto; margin-top: 10px;" });
  const errorEl = el("div.alert", { hidden: true });

  let filtered = [...conversations];

  function renderList() {
    clear(listContainer);
    if (!filtered.length) {
      listContainer.append(el("div.tplc-empty", {}, ["No matching chats found."]));
      return;
    }

    for (const conv of filtered) {
      const contactName = conv.contact?.name || conv.contact?.wa_id || "Customer";
      const isSameChat = String(conv.id) === String(message.conversation_id || message.conversation);

      const sendBtn = el("button.btn.btn--primary.btn--sm", {
        type: "button",
        disabled: isSameChat,
        onclick: async () => {
          sendBtn.disabled = true;
          sendBtn.textContent = "Forwarding…";
          errorEl.hidden = true;
          try {
            const res = await inbox.forward(message.id, conv.id);
            dialog.close();
            onForward?.(conv, res);
          } catch (err) {
            sendBtn.disabled = false;
            sendBtn.textContent = "Send";
            errorEl.textContent = err.message || "Failed to forward message.";
            errorEl.hidden = false;
          }
        },
      }, [isSameChat ? "This Chat" : "Forward"]);

      const item = el("div.na-row", { style: "padding: 10px; display: flex; align-items: center; justify-content: space-between;" }, [
        el("div", {}, [
          el("div", { style: "font-weight: 600; font-size: 13px;" }, [contactName]),
          el("div", { style: "font-size: 11px; opacity: 0.7;" }, [conv.contact?.wa_id || ""]),
        ]),
        sendBtn,
      ]);

      listContainer.append(item);
    }
  }

  searchInput.addEventListener("input", () => {
    const q = searchInput.value.toLowerCase().trim();
    if (!q) {
      filtered = [...conversations];
    } else {
      filtered = conversations.filter((c) => {
        const name = (c.contact?.name || "").toLowerCase();
        const waId = (c.contact?.wa_id || "").toLowerCase();
        return name.includes(q) || waId.includes(q);
      });
    }
    renderList();
  });

  const body = el("div.modal__body", {}, [
    el("div.na-note", {}, ["Select a contact or chat to forward this message."]),
    searchInput,
    errorEl,
    listContainer,
  ]);

  const dialog = modal("Forward Message", body);
  renderList();
  return dialog;
}
