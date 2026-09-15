/**
 * Starred Messages List & Navigation Drawer
 */

import { inbox } from "../api/api.js";
import { clear, el, formatBytes, modal, stamp, toast } from "../core/dom.js";
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

      const card = el("div.akit-card", {}, [
        el("div.akit-row", {}, [
          el("div.akit-row__main", {}, [
            el("div.akit-row__top", {}, [
              icon("starFill", { size: 14, className: "star-gold" }),
              el("strong", {}, [contactName]),
            ]),
            el("div.akit-asset-card__meta", {}, [stamp(item.created_at)]),
            item.body
              ? el("div.akit-body", {}, [item.body])
              : el("div.akit-asset-card__meta", {}, [`[${item.kind || "Attachment"}]`]),
          ]),
          el("div.akit-actions", {}, [
            el("button.btn.btn--ghost.btn--sm", {
              type: "button",
              title: "Unstar message",
              onclick: async () => {
                try {
                  await inbox.star(item.id, false);
                  await fetchStarred();
                } catch (err) {
                  toast(`Unstar failed: ${err.message}`, "err");
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
      ]);

      listContainer.append(card);
    }

    body.append(listContainer);
  }

  fetchStarred();
  return dialog;
}
