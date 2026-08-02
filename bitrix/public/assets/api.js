/**
 * Typed wrapper over the panel's REST contract.
 *
 * Every call goes through apiFetch, so the session cookie and CSRF header are
 * handled in one place (see bitrix-sso.js). Keeping the endpoint strings here
 * means a contract change is a one-file edit.
 */

import { apiFetch } from "./bitrix-sso.js";

export const auth = {
  me: () => apiFetch("/api/auth/me/"),
};

export const catalog = {
  numbers: () => apiFetch("/api/catalog/numbers/"),
  templates: (numberId) => apiFetch(`/api/catalog/numbers/${numberId}/templates/`),
};

export const inbox = {
  conversations({ number, q, limit = 40, offset = 0 } = {}) {
    const query = new URLSearchParams({ limit, offset });
    if (number) query.set("number", number);
    if (q) query.set("q", q);
    return apiFetch(`/api/inbox/conversations/?${query}`);
  },

  messages(conversationId, { before, limit = 40 } = {}) {
    const query = new URLSearchParams({ limit });
    if (before) query.set("before", before);
    return apiFetch(`/api/inbox/conversations/${conversationId}/messages/?${query}`);
  },

  send: (conversationId, body) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/send/`, { method: "POST", body }),

  sendTemplate: (conversationId, body) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/send-template/`, { method: "POST", body }),

  assign: (conversationId, body) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/assign/`, { method: "POST", body }),

  markRead: (conversationId) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/read/`, { method: "POST", body: {} }),

  start: (body) => apiFetch("/api/inbox/start/", { method: "POST", body }),

  uploadMedia(file) {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/inbox/media/upload/", { method: "POST", body: form });
  },
};

/**
 * Collections come back either as a bare array or wrapped in an envelope
 * ({results: []} / {conversations: []}), depending on how DRF is configured for
 * the endpoint. Normalising here keeps that guesswork out of the UI code.
 */
export function asList(payload, key) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const candidate of [key, "results", "items", "data"]) {
    if (candidate && Array.isArray(payload[candidate])) return payload[candidate];
  }
  return [];
}
