/**
 * API wrappers for extras features (Search, Reminders, Reply Buttons).
 * Uses apiFetch from bitrix-sso.js to maintain session cookie + CSRF authentication.
 */

import { apiFetch } from "../core/bitrix-sso.js";

/**
 * Search inbox messages.
 * GET /api/inbox/search/?q=<term>&conversation=<id>&number=<id>&limit=50
 */
export async function searchMessages({ q, conversationId, numberId, limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (conversationId) params.set("conversation", conversationId);
  if (numberId) params.set("number", numberId);
  if (limit) params.set("limit", String(limit));

  return apiFetch(`/api/inbox/search/?${params.toString()}`);
}

/**
 * Create a reminder for a conversation.
 * POST /api/inbox/conversations/<id>/reminders/
 * Body: { due_at, note }
 */
export async function createReminder(conversationId, { due_at, note }) {
  return apiFetch(`/api/inbox/conversations/${conversationId}/reminders/`, {
    method: "POST",
    body: { due_at, note },
  });
}

/**
 * Fetch reminders list.
 * GET /api/inbox/reminders/?open=1 or open=0
 */
export async function getReminders({ open = 1 } = {}) {
  return apiFetch(`/api/inbox/reminders/?open=${open}`);
}

/**
 * Mark a reminder as completed (done).
 * POST /api/inbox/reminders/<id>/
 */
export async function markReminderDone(reminderId) {
  return apiFetch(`/api/inbox/reminders/${reminderId}/`, {
    method: "POST",
  });
}

/**
 * Delete a reminder.
 * DELETE /api/inbox/reminders/<id>/
 */
export async function deleteReminder(reminderId) {
  return apiFetch(`/api/inbox/reminders/${reminderId}/`, {
    method: "DELETE",
  });
}

/**
 * Send interactive reply buttons to a conversation.
 * POST /api/inbox/conversations/<id>/send-buttons/
 * Body: { body, buttons: [{id, title}], header, footer }
 */
export async function sendReplyButtons(conversationId, { body, buttons, header, footer }) {
  const payload = { body, buttons };
  if (header) payload.header = header;
  if (footer) payload.footer = footer;

  return apiFetch(`/api/inbox/conversations/${conversationId}/send-buttons/`, {
    method: "POST",
    body: payload,
  });
}
