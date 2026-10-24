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
 * assistant's mode in that chat, and in a shops chat followup_due_at /
 * followup_label when it will check back with the customer, and followup_note
 * while its automatic follow-up waits for Template B's approval),
 * lead_ai_appointment (the open meeting, or null) and the inbox's own labels
 * ([{id, name, colour}]). The settings carry the shops playbook's
 * shops_facts, brand_name and viewing_agent_name, and desk_agents (who has
 * Lead AI access). The agent desk (desk.js): lead_ai_ai carries a shops chat's
 * track, unit and track_label; a call carries call_label, taken_by, taken_at
 * and takeable on its appointment.
 *
 * The shops media library (shop-media.js): every agent reads it; a panel admin
 * adds, replaces, deletes and reorders its files. Each call that changes it
 * answers with the whole library again; a refused file is 400 {detail}.
 */

import { apiFetch } from "../../core/bitrix-sso.js";
import { asList, inbox, leadbot } from "../../api/api.js";

// A 16 MB video on a slow line takes longer than an ordinary call may.
const UPLOAD_MS = 180000;

function fileForm(fields) {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  return form;
}

/** A library file's id as it may go in a path: a whole number, else nothing. */
function mediaId(id) {
  const n = Number(id);
  return Number.isInteger(n) && n > 0 ? String(n) : "0";
}

export const leadAiApi = {
  /**
   * `label` keeps only the chats carrying that label ("Broker"). The agent desk
   * (desk.js): `track` ("shop", "rent", "sale", "other") keeps one track's chats;
   * `needs` lists the chats that need a person, `today` the visits and calls of
   * today, each row with lead_ai_desk. The first page carries desk_counts.
   */
  chats({ q = "", label = "", track = "", needs = false, today = false, sort = "", unread = false, limit = 40, offset = 0 } = {}) {
    const query = new URLSearchParams({ limit, offset });
    if (q) query.set("q", q);
    if (label) query.set("label", label);
    // Only the chats with a customer message nobody has read yet (the list's Unread filter; views: unread_count > 0).
    if (unread) query.set("unread", "1");
    if (track) query.set("track", track);
    if (needs) query.set("needs", "1");
    else if (today) query.set("today", "1");
    // The hottest leads first (lead_ai_ai.score; the server sorts, the unscored last).
    if (sort === "score" && !needs && !today) query.set("sort", "score");
    return apiFetch(`/api/leadai/chats/?${query}`);
  },

  /** The numbers on the desk's Needs a person and Today buttons: {needs, today}. */
  deskCounts: () => apiFetch("/api/leadai/desk/"),

  /** I'll call: takes the chat's open call. Returns the row; 409 {detail, taken_by} when someone has it. */
  takeCall: (id) => apiFetch(`/api/leadai/chats/${id}/appointment/take/`, { method: "POST", body: {} }),

  chat: (id) => apiFetch(`/api/leadai/chats/${id}/`),

  moveToInbox: (id) => apiFetch(`/api/leadai/chats/${id}/move-to-inbox/`, { method: "POST", body: {} }),

  /**
   * The handover desk (handover_desk.py): the chats handed to a person whose Bitrix responsible the agent is, each the
   * chat and the customer only; an admin may pass another agent's Bitrix user id. `deskDone` is their Done.
   */
  deskMine: ({ agent = "" } = {}) => apiFetch(`/api/leadai/desk/mine/${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`),
  deskDone: (id) => apiFetch(`/api/leadai/chats/${id}/desk/done/`, { method: "POST", body: {} }),

  /** The assistant stops answering this chat until someone resumes it. Returns the row. */
  pauseAi: (id) => apiFetch(`/api/leadai/chats/${id}/pause-ai/`, { method: "POST", body: {} }),

  /** Clears a pause, a stop or a handover. Returns the row. */
  resumeAi: (id) => apiFetch(`/api/leadai/chats/${id}/resume-ai/`, { method: "POST", body: {} }),

  /** The co-pilot (assistant/copilot.py): ask for a draft, say the draft was sent (as it was or edited), drop it. */
  draftAsk: (id, question) => apiFetch(`/api/leadai/chats/${id}/draft/ask/`, { method: "POST", body: { question } }),
  draftUsed: (id, text) => apiFetch(`/api/leadai/chats/${id}/draft/used/`, { method: "POST", body: { text } }),
  draftDismiss: (id) => apiFetch(`/api/leadai/chats/${id}/draft/dismiss/`, { method: "POST", body: {} }),

  /** Reports (assistant/digest.py): {today: {day, stats, text}, digests: [{day, stats, text, sent_to}], digest_hour}. */
  digests: ({ days = 14 } = {}) => apiFetch(`/api/leadai/digests/?days=${Number(days) || 14}`),

  /** Tools → Campaigns: Lead AI campaigns only (all creators), with delivered/read. */
  campaigns: ({ limit = 50, offset = 0 } = {}) =>
    apiFetch(`/api/leadai/campaigns/?limit=${Number(limit) || 50}&offset=${Number(offset) || 0}`),
  campaign: (id) => apiFetch(`/api/leadai/campaigns/${Number(id) || 0}/`),

  /** The community packs (assistant/communities.py): {communities: [{name, aliases, sub_areas, units, units_live, ...}], can_edit}. */
  communities: () => apiFetch("/api/leadai/communities/"),

  /** A panel admin changes one pack (only the keys sent; 400 {detail, errors: {field: message}}) or adds one. */
  updateCommunity: (id, changes) => apiFetch(`/api/leadai/communities/${Number(id) || 0}/`, { method: "PUT", body: changes }),
  createCommunity: (data) => apiFetch("/api/leadai/communities/new/", { method: "POST", body: data }),

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

  /** {can_edit, limits: {video_mb, photo_mb}, shops: [{shop, label, limits, items: [...]}]}, in sending order. */
  shopMedia: () => apiFetch("/api/leadai/shop-media/"),

  /** Adds one file to a shop ("type_1".."type_3", "office"). Returns the library, with `created`. */
  addShopMedia: (shop, file) =>
    apiFetch("/api/leadai/shop-media/", { method: "POST", body: fileForm({ shop, file }), timeoutMs: UPLOAD_MS }),

  /** Another file in the same place of the order. Returns the library. */
  replaceShopMedia: (id, file) =>
    apiFetch(`/api/leadai/shop-media/${mediaId(id)}/replace/`, { method: "POST", body: fileForm({ file }), timeoutMs: UPLOAD_MS }),

  deleteShopMedia: (id) => apiFetch(`/api/leadai/shop-media/${mediaId(id)}/`, { method: "DELETE" }),

  /** Every file id of the shop, once, in the new order. Returns the library. */
  reorderShopMedia: (shop, ids) => apiFetch("/api/leadai/shop-media/reorder/", { method: "POST", body: { shop, ids } }),
};

export { asList, inbox };
