/**
 * Starred Messages List & Navigation Drawer
 */

import { inbox } from "../api/api.js";
import { clear, el, formatBytes, modal, stamp } from "../core/dom.js";
import { icon } from "../core/icons.js";

export function openStarredMessagesModal({ conversationId, onNavigateToMessage } = {}) {
  const body = el("div.modal__body.na", {}, [el("div.na-note", {}, ["Loading starred messages…"])]);
  const dialog = modal("Starred Messages", body, { wide: true });

  let starredList = [];

  async function fetchStarred() {
    clear(body).append(el("div.na-note", {}, ["Loading starred messages…"]));
    try {
      starredList = await inbox.starredList(conversationId);
      render();
    } catch (err) {
      clear(body).append(el("div.alert", {}, [`Failed to load starred messages: ${err.message}`]));
    }
  }

  function render() {
    clear(body);
    if (!starredList.length) {
      body.append(el("div.tplc-empty", {}, ["No starred messages yet."]));
      return;
    }

    const listContainer = el("div.na-rows");

    for (const item of starredList) {
      const conv = item.conversation || {};
      const contactName = conv.contact?.name || conv.contact?.wa_id || "Customer";

      const card = el("div.na-row", { style: "padding: 12px; border-radius: 8px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);" }, [
        el("div.na-head", {}, [
          el("div.na-who", {}, [
            el("div.na-title", { style: "font-weight: 600; display: flex; align-items: center; gap: 6px;" }, [
              icon("starFill", { size: 14, className: "star-gold" }),
              contactName,
            ]),
            el("div.na-phone", { style: "font-size: 11px; opacity: 0.7;" }, [stamp(item.created_at)]),
          ]),
          el("div.na-flags", {}, [
            el("button.btn.btn--ghost.btn--sm", {
              type: "button",
              title: "Unstar message",
              onclick: async () => {
                try {
                  await inbox.star(item.id, false);
                  await fetchStarred();
                } catch (err) {
                  alert(`Unstar failed: ${err.message}`);
                }
              },
            }, [icon("star", { size: 14 })]),
            el("button.btn.btn--primary.btn--sm", {
              type: "button",
              onclick: () => {
                dialog.close();
                onNavigateToMessage?.(conv.id, item.id);
              },
            }, ["Go to Chat"]),
          ]),
        ]),
        el("div.na-body", { style: "grid-template-columns: 1fr; margin-top: 8px;" }, [
          item.body ? el("div", { style: "font-size: 13px; white-space: pre-wrap;" }, [item.body]) : el("div", { style: "font-size: 12px; font-style: italic; opacity: 0.7;" }, [`[${item.kind || "Attachment"}]`]),
        ]),
      ]);

      listContainer.append(card);
    }

    body.append(listContainer);
  }

  fetchStarred();
  return dialog;
}
