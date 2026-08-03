/**
 * Typed wrapper over the panel's REST contract.
 *
 * Every call goes through apiFetch, so the session cookie and CSRF header are
 * handled in one place (see bitrix-sso.js). Keeping the endpoint strings here
 * means a contract change is a one-file edit.
 */

import { apiFetch, csrfToken, SsoError } from "../core/bitrix-sso.js";

export const auth = {
  me: () => apiFetch("/api/auth/me/"),
  updateProfile: (data) => apiFetch("/api/auth/me/", { method: "POST", body: data }),
};

/**
 * An agent with no number assigned cannot do anything in the panel, so instead
 * of an empty inbox they get to say which number they need. Admins read those
 * notes and act on them from the same place they do the assigning.
 */
export const access = {
  request: (message) => apiFetch("/api/accounts/access-request/", { method: "POST", body: { message } }),

  /** Admin only. */
  list: () => apiFetch("/api/accounts/access-requests/"),

  resolve: (id) => apiFetch(`/api/accounts/access-requests/${id}/resolve/`, { method: "POST", body: {} }),
};

export const catalog = {
  // For an admin this also carries each number's assigned agents.
  numbers: () => apiFetch("/api/catalog/numbers/"),
  templates: (numberId) => apiFetch(`/api/catalog/numbers/${numberId}/templates/`),
  allTemplates: (params = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.q) query.set("q", params.q);
    const qs = query.toString();
    return apiFetch(`/api/catalog/templates/all/${qs ? `?${qs}` : ""}`);
  },
  createTemplate: (data) => apiFetch("/api/catalog/templates/create/", { method: "POST", body: data }),
  syncTemplates: () => apiFetch("/api/catalog/sync/", { method: "POST", body: { what: "templates" } }),

  /** Admin only. */
  agents: () => apiFetch("/api/catalog/agents/"),
  setAgentAdmin: (agentId, isWaAdmin) =>
    apiFetch(`/api/catalog/agents/${agentId}/admin/`, { method: "POST", body: { is_wa_admin: isWaAdmin } }),

  /** Renames a number. An empty label clears it and `title` falls back. */
  renameNumber: (numberId, label) =>
    apiFetch(`/api/catalog/numbers/${numberId}/`, { method: "PATCH", body: { label } }),

  /** Replaces the whole roster for a number — send the state you want. */
  setNumberAgents: (numberId, agents) =>
    apiFetch(`/api/catalog/numbers/${numberId}/agents/`, { method: "PUT", body: { agents } }),
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

  sendLocation: (conversationId, data) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/send-location/`, { method: "POST", body: data }),

  forward: (messageId, conversationId) =>
    apiFetch(`/api/inbox/messages/${messageId}/forward/`, { method: "POST", body: { conversation_id: conversationId } }),

  retry: (messageId) =>
    apiFetch(`/api/inbox/messages/${messageId}/retry/`, { method: "POST", body: {} }),

  star: (messageId, starred) =>
    apiFetch(`/api/inbox/messages/${messageId}/star/`, { method: "POST", body: { starred } }),

  starredList: (conversationId) => {
    const qs = conversationId ? `?conversation=${conversationId}` : "";
    return apiFetch(`/api/inbox/starred/${qs}`);
  },

  quickReplies: () => apiFetch("/api/inbox/quick-replies/"),
  createQuickReply: (data) => apiFetch("/api/inbox/quick-replies/", { method: "POST", body: data }),
  deleteQuickReply: (id) => apiFetch(`/api/inbox/quick-replies/${id}/`, { method: "DELETE" }),

  exportUrl: (conversationId, fmt = "txt") => `/api/inbox/conversations/${conversationId}/export/?fmt=${fmt}`,

  assign: (conversationId, body) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/assign/`, { method: "POST", body }),

  markRead: (conversationId) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/read/`, { method: "POST", body: {} }),

  start: (body) => apiFetch("/api/inbox/start/", { method: "POST", body }),

  /**
   * Uploads an attachment and reports progress.
   *
   * XMLHttpRequest rather than fetch: fetch still cannot report upload
   * progress, and a 100 MB document sent over a phone connection needs a bar
   * and a cancel button rather than a frozen dialog.
   *
   * @returns {{promise: Promise<{media_id: string}>, abort: () => void}}
   */
  uploadMedia(file, { conversationId, numberId, onProgress } = {}) {
    const form = new FormData();
    form.append("file", file);
    if (conversationId) form.append("conversation_id", conversationId);
    // New Contact uploads a template's header image before any conversation
    // exists, so the number is the only thing available to bill the upload to.
    if (numberId) form.append("number_id", numberId);

    const xhr = new XMLHttpRequest();
    const promise = new Promise((resolve, reject) => {
      xhr.open("POST", `${window.location.origin}/api/inbox/media/upload/`);
      xhr.withCredentials = true;
      xhr.setRequestHeader("Accept", "application/json");
      const csrf = csrfToken();
      if (csrf) xhr.setRequestHeader("X-CSRFToken", csrf);

      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onProgress?.(event.loaded / event.total);
      });

      xhr.addEventListener("load", () => {
        let payload = null;
        try {
          payload = JSON.parse(xhr.responseText);
        } catch {
          /* handled below */
        }
        if (xhr.status >= 200 && xhr.status < 300 && payload) {
          resolve(payload);
        } else {
          reject(
            new SsoError(
              `http_${xhr.status}`,
              payload?.detail || `Upload failed (HTTP ${xhr.status})`,
              payload
            )
          );
        }
      });

      xhr.addEventListener("error", () => reject(new SsoError("network", "The connection dropped during the upload.")));
      xhr.addEventListener("abort", () => reject(new SsoError("aborted", "The upload was cancelled.")));
      xhr.send(form);
    });

    return { promise, abort: () => xhr.abort() };
  },

  sharedAssets: (params = {}) => {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.kind) query.set("kind", params.kind);
    const qs = query.toString();
    return apiFetch(`/api/inbox/shared-assets/${qs ? `?${qs}` : ""}`);
  },

  uploadSharedAsset(file, title) {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    return apiFetch("/api/inbox/shared-assets/", { method: "POST", body: form });
  },

  deleteSharedAsset(id) {
    return apiFetch(`/api/inbox/shared-assets/${id}/`, { method: "DELETE" });
  },

  labels: () => apiFetch("/api/inbox/labels/"),
  setFlags: (conversationId, flags) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/flags/`, { method: "POST", body: flags }),
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
