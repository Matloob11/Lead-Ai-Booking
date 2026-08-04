/**
 * REST API Routes: Conversations and Messages
 *
 * Scoped by phone, not by who answered. An agent assigned to a number sees
 * every conversation on it — see sessions/assignments.js for why.
 */

import express from "express";
import { q, one } from "../../db.js";
import { visibleSessionIds } from "../identity.js";
import { sessionIdsForAgent } from "../../sessions/assignments.js";

const router = express.Router();

// GET /api/conversations?session_id=&agent_id=&limit=&offset=
router.get("/", async (req, res, next) => {
  try {
    const sessionId = req.query.session_id ? Number(req.query.session_id) : null;
    const limit = Math.min(100, Math.max(1, Number(req.query.limit || 40)));
    const offset = Math.max(0, Number(req.query.offset || 0));

    // What the caller is allowed to see, before anything they asked for.
    const allowed = await visibleSessionIds(req.identity);

    // `agent_id` narrows the view to one agent's phones. It is a filter an
    // admin uses to look at somebody's work — it can only ever subtract from
    // `allowed`, never reach past it.
    let scope = allowed;
    if (req.query.agent_id) {
      const theirs = await sessionIdsForAgent(req.query.agent_id);
      scope = allowed === null ? theirs : allowed.filter((id) => theirs.includes(id));
    }

    if (sessionId !== null) {
      const permitted = scope === null || scope.includes(sessionId);
      // Nothing here, rather than "not allowed": whether a phone exists is
      // itself something only the people who hold it need to know.
      if (!permitted) return res.json([]);
      scope = [sessionId];
    }

    if (scope !== null && !scope.length) return res.json([]);

    let whereClause = "";
    const params = [limit, offset];

    if (scope !== null) {
      whereClause = "WHERE conv.session_id = ANY($3::bigint[])";
      params.push(scope);
    }

    const rows = await q(
      `SELECT
         conv.id,
         conv.session_id,
         conv.contact_id,
         conv.is_group,
         conv.subject,
         conv.last_message_at,
         conv.last_message_preview,
         conv.last_message_kind,
         conv.unread_count,
         conv.created_at,
         c.wa_id AS contact_wa_id,
         c.profile_name AS contact_profile_name,
         c.display_name AS contact_display_name
       FROM qr_conversation conv
       JOIN qr_contact c ON conv.contact_id = c.id
       ${whereClause}
       ORDER BY conv.last_message_at DESC NULLS LAST
       LIMIT $1 OFFSET $2`,
      params
    );

    const conversations = rows.map((r) => ({
      id: Number(r.id),
      session_id: Number(r.session_id),
      is_group: r.is_group,
      subject: r.subject,
      last_message_at: r.last_message_at,
      last_message_preview: r.last_message_preview,
      last_message_kind: r.last_message_kind,
      unread_count: r.unread_count,
      contact: {
        id: Number(r.contact_id),
        wa_id: r.contact_wa_id,
        name: r.contact_display_name || r.contact_profile_name || r.contact_wa_id,
      },
    }));

    res.json(conversations);
  } catch (err) {
    next(err);
  }
});

/**
 * Whether this caller may touch one conversation, by id.
 *
 * The list route is scoped, but a conversation id is guessable — it counts up
 * from 1. Without this an agent could read any thread on any phone in the
 * building by typing a different number. Answering 404 rather than 403 keeps
 * whether the conversation exists at all to the people who hold the phone.
 */
async function reachable(req, conversationId) {
  const owner = await one(`SELECT session_id FROM qr_conversation WHERE id = $1`, [
    conversationId,
  ]);
  if (!owner) return false;
  const allowed = await visibleSessionIds(req.identity);
  return allowed === null || allowed.includes(Number(owner.session_id));
}

// GET /api/conversations/:id/messages?limit=&before=
router.get("/:id/messages", async (req, res, next) => {
  try {
    const conversationId = Number(req.params.id);
    const limit = Math.min(100, Math.max(1, Number(req.query.limit || 40)));
    const before = req.query.before ? Number(req.query.before) : null;

    if (!(await reachable(req, conversationId))) {
      return res.status(404).json({ detail: "Conversation not found" });
    }

    let whereClause = "WHERE m.conversation_id = $1";
    const params = [conversationId, limit];

    // "Older than that one" in the order the thread is actually read in, which
    // since the history import is no longer the order rows were written in: an
    // imported message is months old and carries a brand-new id. Row-value
    // comparison keeps the cursor and the sort agreeing on what "before" means.
    if (before) {
      whereClause +=
        " AND (m.created_at, m.id) < (SELECT created_at, id FROM qr_message WHERE id = $3)";
      params.push(before);
    }

    // Fetch descending for pagination
    const rows = await q(
      `SELECT
         m.id,
         m.conversation_id,
         m.direction,
         m.kind,
         m.wamid,
         m.body,
         m.media_id,
         m.reply_to_id,
         m.reactions,
         m.author_wa_id,
         m.status,
         m.error_detail,
         m.created_at,
         m.delivered_at,
         m.read_at,
         med.file_path AS media_file_path,
         med.mime_type AS media_mime_type,
         med.file_name AS media_file_name,
         med.size_bytes AS media_size_bytes,
         med.downloaded AS media_downloaded,
         med.download_error AS media_error
       FROM qr_message m
       LEFT JOIN qr_media med ON m.media_id = med.id
       ${whereClause}
       ORDER BY m.created_at DESC, m.id DESC
       LIMIT $2`,
      params
    );

    // Return in OLDEST-FIRST chronological order
    const messages = rows.reverse().map((r) => ({
      id: Number(r.id),
      conversation_id: Number(r.conversation_id),
      direction: r.direction,
      kind: r.kind,
      wamid: r.wamid,
      body: r.body,
      status: r.status,
      error_detail: r.error_detail,
      reply_to_id: r.reply_to_id ? Number(r.reply_to_id) : null,
      reactions: r.reactions || {},
      author_wa_id: r.author_wa_id,
      created_at: r.created_at,
      media_url: r.media_id ? `/api/media/${r.media_id}` : null,
      // The same bytes, shown rather than downloaded. Which of the two a
      // message wants is the panel's decision, so it is given both.
      media_inline_url: r.media_id ? `/api/media/${r.media_id}/inline` : null,
      // Without this the panel could only guess a picture from `kind`, and had
      // no way at all to tell a voice note from a document.
      media_mime: r.media_mime_type || null,
      media_name: r.media_file_name || null,
      media_size: r.media_size_bytes || null,
      // Whether the bytes are actually here. A message and its file are stored
      // separately, so a download that failed leaves a perfectly readable
      // message pointing at nothing — and the panel, told only that there is an
      // attachment, drew a broken image in the middle of the conversation.
      media_downloaded: r.media_id ? Boolean(r.media_downloaded) : null,
    }));

    res.json(messages);
  } catch (err) {
    next(err);
  }
});

/**
 * POST /api/conversations/:id/read — the chat is open in front of somebody.
 *
 * Nothing cleared this before, so the badge only ever counted upwards and a
 * chat the agent was reading kept a number beside it.
 *
 * There is no matching "mark unread". The count answers one question — what
 * has arrived that nobody has looked at — and the next inbound message rebuilds
 * it anyway.
 */
router.post("/:id/read", async (req, res, next) => {
  try {
    const conversationId = Number(req.params.id);

    if (!(await reachable(req, conversationId))) {
      return res.status(404).json({ detail: "Conversation not found" });
    }

    const row = await one(
      `UPDATE qr_conversation SET unread_count = 0 WHERE id = $1
       RETURNING id, unread_count`,
      [conversationId]
    );

    res.json({ id: Number(row.id), unread_count: Number(row.unread_count) });
  } catch (err) {
    next(err);
  }
});

export default router;
