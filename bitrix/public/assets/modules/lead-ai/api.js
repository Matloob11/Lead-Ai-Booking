/**
 * Lead AI REST calls.
 *
 * Its own list, the assistant's state per chat, the meeting it booked, its
 * settings and the way back to the main inbox live under /api/leadai/.
 * Reading and answering a chat reuse the inbox endpoints: they check access
 * per thread, so a Lead AI chat opens and sends there like any other.
 *
 * A chat row (list, detail, and every POST below) carries lead_ai_info (the
 * campaign, and its playbook: "general" or "ic_shops"), lead_ai_ai (the
 * assistant's mode in that chat), lead_ai_appointment (the open meeting, or
 * null) and the inbox's own labels ([{id, name, colour}]).
 */

import { apiFetch } from "../../core/bitrix-sso.js";
import { asList, inbox, leadbot } from "../../api/api.js";

export const leadAiApi = {
  /** `label` keeps only the chats carrying that label ("Broker"). */
  chats({ q = "", label = "", limit = 40, offset = 0 } = {}) {
    const query = new URLSearchParams({ limit, offset });
    if (q) query.set("q", q);
    if (label) query.set("label", label);
    return apiFetch(`/api/leadai/chats/?${query}`);
  },

  chat: (id) => apiFetch(`/api/leadai/chats/${id}/`),

  moveToInbox: (id) => apiFetch(`/api/leadai/chats/${id}/move-to-inbox/`, { method: "POST", body: {} }),

  /** The assistant stops answering this chat until someone resumes it. Returns the row. */
  pauseAi: (id) => apiFetch(`/api/leadai/chats/${id}/pause-ai/`, { method: "POST", body: {} }),

  /** Clears a pause, a stop or a handover. Returns the row. */
  resumeAi: (id) => apiFetch(`/api/leadai/chats/${id}/resume-ai/`, { method: "POST", body: {} }),

  /** Cancels the chat's open meeting (409 when there is none). Returns the row. */
  cancelAppointment: (id) =>
    apiFetch(`/api/leadai/chats/${id}/appointment/cancel/`, { method: "POST", body: {} }),

  /** The assistant's switch, test numbers, office and limits; everyone may read them. */
  settings: () => apiFetch("/api/leadai/settings/"),

  /**
   * Only the keys being changed. The server decides who may change what
   * (400 {detail, errors: {field: message}}, 403 {detail}).
   */
  saveSettings: (changes) => apiFetch("/api/leadai/settings/", { method: "PUT", body: changes }),

  /** Sara's lead automations (apps/leadbot), shown on their own tab as before. */
  saraBoard: () => leadbot.board(),
};

export { asList, inbox };
