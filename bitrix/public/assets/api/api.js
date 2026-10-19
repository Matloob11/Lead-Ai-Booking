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

export const leadbot = {
  board: () => apiFetch("/api/leadbot/board/"),
};

export const reports = {
  summary: (days = 7) => apiFetch(`/api/reports/summary/?days=${days}`),
  agents: (days = 7) => apiFetch(`/api/reports/agents/?days=${days}`),
  numbers: (days = 7) => apiFetch(`/api/reports/numbers/?days=${days}`),
  failures: (days = 7) => apiFetch(`/api/reports/failures/?days=${days}`),
  templates: (days = 7) => apiFetch(`/api/reports/templates/?days=${days}`),
};

/**
 * Multipart POST with upload progress.
 *
 * XMLHttpRequest rather than fetch: fetch still cannot report upload
 * progress, and a 100 MB document sent over a phone connection needs a bar
 * and a cancel button rather than a frozen dialog.
 *
 * @returns {{promise: Promise<object>, abort: () => void}}
 */
function xhrUpload(path, form, { onProgress } = {}) {
  const xhr = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    xhr.open("POST", `${window.location.origin}${path}`);
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
}

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
  createTemplateBulk: (data) =>
    apiFetch("/api/catalog/templates/create-bulk/", { method: "POST", body: data }),
  deployTemplate: (id, data = {}) =>
    apiFetch(`/api/catalog/templates/${id}/deploy/`, { method: "POST", body: data }),
  deleteTemplate: (id) => apiFetch(`/api/catalog/templates/${id}/`, { method: "DELETE" }),
  purgeTemplateMeta: (id) =>
    apiFetch(`/api/catalog/templates/${id}/purge-meta/`, { method: "POST" }),
  suggestUtilityTemplates: (data) =>
    apiFetch("/api/catalog/templates/utility-suggestions/", { method: "POST", body: data }),
  syncTemplates: (wabaBusinessId) =>
    apiFetch("/api/catalog/sync/", {
      method: "POST",
      body: {
        what: "templates",
        ...(wabaBusinessId ? { waba_business_id: wabaBusinessId } : {}),
      },
      // One business account is a single Meta call. "All my numbers" is queued
      // and returns immediately, so it must not sit on the 45s panel limit.
      timeoutMs: wabaBusinessId ? 60000 : 20000,
    }),

  /** Can this server take a sample image/video/PDF for a template header? */
  headerMediaStatus: () => apiFetch("/api/catalog/templates/header-media/"),

  /**
   * The sample a media-header template is reviewed against. Meta answers
   * with a handle, which goes into the create call as header_handle.
   */
  uploadTemplateHeaderMedia(file, format, { wabaId = "", onProgress } = {}) {
    const form = new FormData();
    form.append("file", file);
    form.append("format", format);
    if (wabaId) form.append("waba_business_id", wabaId);
    return xhrUpload("/api/catalog/templates/header-media/", form, { onProgress });
  },

  /** Admin only. */
  agents: () => apiFetch("/api/catalog/agents/"),
  setAgentAdmin: (agentId, isWaAdmin) =>
    apiFetch(`/api/catalog/agents/${agentId}/admin/`, { method: "POST", body: { is_wa_admin: isWaAdmin } }),
  /** Admin only — Official API / Linked phones / Panel Admin flags. */
  setAgentAccess: (agentId, body) =>
    apiFetch(`/api/catalog/agents/${agentId}/admin/`, { method: "POST", body }),

  /** Renames a number. An empty label clears it and `title` falls back. */
  renameNumber: (numberId, body) =>
    apiFetch(`/api/catalog/numbers/${numberId}/`, {
      method: "PATCH",
      body: typeof body === "string" ? { label: body } : body,
    }),

  /** Replaces the whole roster for a number — send the state you want. */
  setNumberAgents: (numberId, agents) =>
    apiFetch(`/api/catalog/numbers/${numberId}/agents/`, { method: "PUT", body: { agents } }),

  /** Probe alots for Phone Number ID / Business ID before saving a manual row. */
  testNumber: (data) =>
    apiFetch("/api/catalog/numbers/test/", { method: "POST", body: data }),

  /** Create a manually typed Official API number (admin). */
  createNumber: (data) =>
    apiFetch("/api/catalog/numbers/", { method: "POST", body: data }),

  /** Admin: pull channel list from alots into the local catalogue. */
  syncNumbers: () => apiFetch("/api/catalog/sync/", { method: "POST", body: { what: "numbers" } }),
};

export const crm = {
  /**
   * Every CRM record carrying this number — lead, contact, or an Owner Data
   * item. Answered by our own backend rather than by BX24, because the search
   * takes several Bitrix calls and the server already has to get it right for
   * the timeline mirror.
   */
  whereis(phone) {
    return apiFetch(`/api/crm/whereis/?phone=${encodeURIComponent(phone)}`);
  },

  /**
   * Makes the record this number has not got yet and copies the conversation
   * into its timeline. `where` is "lead" or "owner_data".
   *
   * Refuses with 409 if the number turns out to be in the CRM after all — two
   * leads for one customer is the problem this portal already has, and one
   * created from here would be our own doing.
   */
  createRecord(conversationId, where) {
    return apiFetch("/api/crm/create/", {
      method: "POST",
      body: { conversation: conversationId, where },
    });
  },
};

/**
 * The QR-linked phones, and who covers them.
 *
 * Separate from `catalog` because these are not our numbers: they live in the
 * OpenWA gateway, are identified by a UUID it issues, and can disappear from
 * under us if somebody unlinks a handset there. Admin only, both ends.
 */
export const linkedPhones = {
  list: () => apiFetch("/api/auth/openwa-sessions/"),

  /** Replaces the roster for one phone — send the state you want, not a change. */
  setAgents: (sessionId, agents, label) =>
    apiFetch(`/api/auth/openwa-sessions/${encodeURIComponent(sessionId)}/agents/`, {
      method: "PUT",
      body: { agents, label },
    }),
};

export const inbox = {
  conversations({ number, q, limit = 40, offset = 0, rotate = false } = {}) {
    const query = new URLSearchParams({ limit, offset });
    if (number) query.set("number", number);
    if (q) query.set("q", q);
    if (rotate) query.set("rotate", "1");
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

  conversationTemplates: (conversationId) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/templates/`),

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
   * Uploads an attachment and reports progress — see xhrUpload.
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
    return xhrUpload("/api/inbox/media/upload/", form, { onProgress });
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
  createLabel: (data) => apiFetch("/api/inbox/labels/", { method: "POST", body: data }),
  deleteLabel: (id) => apiFetch(`/api/inbox/labels/${id}/`, { method: "DELETE" }),
  setFlags: (conversationId, flags) =>
    apiFetch(`/api/inbox/conversations/${conversationId}/flags/`, { method: "POST", body: flags }),
};

/**
 * Agent AI cover: per-chat context plus a global desk that can take new / all /
 * selected chats while the agent is away.
 */
export const inboxAi = {
  desk: () => apiFetch("/api/inboxai/desk/"),
  saveDesk: (data) => apiFetch("/api/inboxai/desk/", { method: "PUT", body: data }),
  cover: (conversationId) => apiFetch(`/api/inboxai/conversations/${conversationId}/cover/`),
  saveCover: (conversationId, data) =>
    apiFetch(`/api/inboxai/conversations/${conversationId}/cover/`, { method: "PUT", body: data }),
  candidates: (q = "") => {
    const query = new URLSearchParams();
    if (q) query.set("q", q);
    const qs = query.toString();
    return apiFetch(`/api/inboxai/candidates/${qs ? `?${qs}` : ""}`);
  },
  healthSummary: () => apiFetch("/api/inboxai/health/summary/"),
  healthList: (colour) =>
    apiFetch(`/api/inboxai/health/list/?colour=${encodeURIComponent(colour)}`),
  healthAllowGreen: (conversationId, password) =>
    apiFetch("/api/inboxai/health/allow-green/", {
      method: "POST",
      body: { conversation_id: conversationId, password },
    }),
  healthReclassifyFalseRed: () =>
    apiFetch("/api/inboxai/health/reclassify-false-red/", { method: "POST", body: {} }),
  healthAnalyse: () => apiFetch("/api/inboxai/health/analyse/", { method: "POST", body: {} }),
};

/**
 * Agent report & feedback for the Official API panel. Attachments are image
 * or video; only admins mark a report solved.
 */
export const feedback = {
  list: (status) => {
    const query = new URLSearchParams();
    if (status) query.set("status", status);
    const qs = query.toString();
    return apiFetch(`/api/feedback/${qs ? `?${qs}` : ""}`);
  },
  create: ({ body, files }) => {
    const form = new FormData();
    form.append("body", body || "");
    for (const file of files || []) form.append("files", file);
    return apiFetch("/api/feedback/", { method: "POST", body: form });
  },
  solve: (id, note) =>
    apiFetch(`/api/feedback/${id}/solve/`, { method: "POST", body: { note: note || "" } }),
};

/**
 * Bulk approved-template campaigns. Recipients from paste and/or CSV; every
 * number is matched or created in Owner Data (SPA 1042).
 */
export const campaigns = {
  list: () => apiFetch("/api/campaigns/"),
  get: (id) => apiFetch(`/api/campaigns/${id}/`),
  preview({ recipients_text = "", csv = null, template_id = null } = {}) {
    const form = new FormData();
    form.append("recipients_text", recipients_text || "");
    if (template_id) form.append("template_id", String(template_id));
    if (csv) form.append("csv", csv);
    return apiFetch("/api/campaigns/preview/", { method: "POST", body: form });
  },
  create({
    number_id,
    template_id,
    name = "",
    recipients_text = "",
    csv = null,
    variables = {},
    header_variables = {},
    button_variables = {},
    header_media_id = "",
  } = {}) {
    const form = new FormData();
    form.append("number_id", String(number_id));
    form.append("template_id", String(template_id));
    form.append("name", name || "");
    form.append("recipients_text", recipients_text || "");
    form.append("variables", JSON.stringify(variables || {}));
    form.append("header_variables", JSON.stringify(header_variables || {}));
    form.append("button_variables", JSON.stringify(button_variables || {}));
    if (header_media_id) form.append("header_media_id", header_media_id);
    if (csv) form.append("csv", csv);
    return apiFetch("/api/campaigns/", { method: "POST", body: form });
  },
  resendSkipped: (id, numberId) =>
    apiFetch(`/api/campaigns/${id}/resend-skipped/`, {
      method: "POST",
      body: numberId ? { number_id: numberId } : {},
    }),
};

/**
 * Excel campaigns: one sheet split across several numbers, so many per
 * number. Separate from `campaigns` on purpose — that screen is untouched.
 */
function bulkForm(fields, file) {
  const form = new FormData();
  if (file) form.append("file", file);
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined || value === null) continue;
    form.append(key, typeof value === "object" ? JSON.stringify(value) : String(value));
  }
  return form;
}

export const bulkCampaigns = {
  inspect: (file) =>
    apiFetch("/api/campaigns/bulk/inspect/", { method: "POST", body: bulkForm({}, file) }),
  preview: ({ file, template_id, mapping, number_ids, per_number_cap }) =>
    apiFetch("/api/campaigns/bulk/preview/", {
      method: "POST",
      body: bulkForm({ template_id, mapping, number_ids, per_number_cap }, file),
    }),
  create: ({ file, ...fields }) =>
    apiFetch("/api/campaigns/bulk/", { method: "POST", body: bulkForm(fields, file) }),
  list: () => apiFetch("/api/campaigns/bulk/"),
  get: (id) => apiFetch(`/api/campaigns/bulk/${id}/`),
  cancel: (id) => apiFetch(`/api/campaigns/bulk/${id}/cancel/`, { method: "POST", body: {} }),
};

export const rotateCampaigns = {
  pool: () => apiFetch("/api/campaigns/rotate/pool/"),
  history: () => apiFetch("/api/campaigns/rotate/history/"),
  get: (id) => apiFetch(`/api/campaigns/rotate/${id}/`),
  start: ({ file, mapping, header_media_ids }) =>
    apiFetch("/api/campaigns/rotate/start/", {
      method: "POST",
      body: bulkForm({ mapping, header_media_ids }, file),
    }),
  resend: (id) => apiFetch(`/api/campaigns/rotate/${id}/resend/`, { method: "POST", body: {} }),
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
