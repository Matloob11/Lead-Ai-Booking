/**
 * How likely a linked phone is to be banned, from what it has actually done.
 *
 * A QR-linked number is a personal WhatsApp account. It has no approved
 * templates, no rate limit negotiated with Meta, and no appeal worth the name —
 * when one is banned it is banned, and the conversations on it stop. The
 * behaviour WhatsApp acts on is well known and none of it is subtle: messaging
 * a lot of people who never wrote first, being ignored by most of them, and
 * doing either quickly on a number nobody has known for long.
 *
 * All three are things this database already records, so they are counted and
 * said out loud rather than left for somebody to notice afterwards.
 *
 * These are honest heuristics and not a prediction. WhatsApp does not publish
 * its thresholds and does not tell anybody why a number went; blocks and
 * reports, which matter most of all, are invisible from here. What this can say
 * truthfully is "this number is behaving the way banned numbers behave", and
 * that is what it says.
 */

import express from "express";
import { q } from "../../db.js";
import { visibleSessionIds } from "../identity.js";
import * as store from "../../sessions/store.js";

const router = express.Router();

/**
 * Where "a lot" begins.
 *
 * Set from what an agent answering chats actually does rather than from a
 * number Meta published, because Meta has published none. A person replying to
 * customers all day sends busily but starts few conversations, and almost
 * everyone they do start replies. A number being used for outreach inverts
 * both, and that inversion is the signal — not the raw volume.
 */
const LIMITS = {
  // Conversations this phone started, in a day.
  newContacts: { watch: 15, high: 30 },
  // Everything it sent, in a day.
  outbound: { watch: 150, high: 300 },
  // Share of the conversations it started in a week that never got a reply.
  // Ignored below `minStarted`, where the share is noise rather than a pattern.
  unreplied: { watch: 0.4, high: 0.6, minStarted: 20 },
  // A number linked days ago is watched harder than one in use for months.
  youngDays: 3,
  youngNewContacts: 10,
};

/**
 * Everything worth knowing about one phone's recent behaviour.
 *
 * Every window is measured on when a message was **sent**, never on when this
 * database learned of it. The difference is the whole feature: the history
 * import writes months of conversation in an afternoon, so counting rows by
 * their creation time asked "what did we import today" and answered "68 new
 * conversations" for a phone that had sent 22 messages. Every freshly linked
 * number would have been declared at risk of a ban on the day it was linked,
 * which is how a warning gets ignored for good.
 *
 * How long the number has been in use is read the same way — from the oldest
 * message on it, not from when somebody scanned its QR code. A phone linked
 * this morning carrying six months of conversation is not a new number.
 */
async function signalsFor(sessionId) {
  const rows = await q(
    `WITH mine AS (
       SELECT m.id, m.conversation_id, m.direction, m.status, m.created_at
         FROM qr_message m
         JOIN qr_conversation c ON c.id = m.conversation_id
        WHERE c.session_id = $1
     ),
     opened AS (
       SELECT DISTINCT ON (conversation_id)
              conversation_id, direction, created_at
         FROM mine
        ORDER BY conversation_id, created_at, id
     ),
     replied AS (
       SELECT DISTINCT conversation_id FROM mine WHERE direction = 'in'
     )
     SELECT
       (SELECT count(*) FROM mine
         WHERE direction = 'out' AND created_at > now() - interval '24 hours') AS outbound_24h,
       (SELECT count(*) FROM mine
         WHERE direction = 'out' AND status = 'failed'
           AND created_at > now() - interval '24 hours')                       AS failed_24h,
       (SELECT count(*) FROM opened
         WHERE direction = 'out' AND created_at > now() - interval '24 hours') AS new_contacts_24h,
       (SELECT count(*) FROM opened
         WHERE direction = 'out' AND created_at > now() - interval '7 days')   AS started_7d,
       (SELECT count(*) FROM opened o
         WHERE o.direction = 'out' AND o.created_at > now() - interval '7 days'
           AND NOT EXISTS (SELECT 1 FROM replied r
                            WHERE r.conversation_id = o.conversation_id))      AS ignored_7d,
       (SELECT min(created_at) FROM mine)                                      AS oldest_message`,
    [sessionId]
  );

  const r = rows[0] || {};
  const started = Number(r.started_7d || 0);
  return {
    outbound24h: Number(r.outbound_24h || 0),
    failed24h: Number(r.failed_24h || 0),
    newContacts24h: Number(r.new_contacts_24h || 0),
    started7d: started,
    ignored7d: Number(r.ignored_7d || 0),
    ignoredShare: started ? Number(r.ignored_7d || 0) / started : 0,
    oldestMessage: r.oldest_message || null,
  };
}

/**
 * A level and the reasons for it.
 *
 * Every reason is a sentence naming the number behind it. "High risk" on its
 * own tells an agent to worry without telling them what to stop doing.
 */
function assess(signals, ageDays) {
  const reasons = [];
  let level = "ok";
  const raise = (to) => {
    if (to === "high" || (to === "watch" && level === "ok")) level = to;
  };

  if (signals.newContacts24h >= LIMITS.newContacts.high) {
    raise("high");
    reasons.push(
      `${signals.newContacts24h} conversations started with people who had not written first, in 24 hours. This is the behaviour WhatsApp bans numbers for.`
    );
  } else if (signals.newContacts24h >= LIMITS.newContacts.watch) {
    raise("watch");
    reasons.push(
      `${signals.newContacts24h} new conversations started in 24 hours. Messaging people who have not written first is what WhatsApp watches most closely.`
    );
  }

  if (signals.outbound24h >= LIMITS.outbound.high) {
    raise("high");
    reasons.push(`${signals.outbound24h} messages sent in 24 hours from one handset.`);
  } else if (signals.outbound24h >= LIMITS.outbound.watch) {
    raise("watch");
    reasons.push(`${signals.outbound24h} messages sent in 24 hours.`);
  }

  if (signals.started7d >= LIMITS.unreplied.minStarted) {
    const percent = Math.round(signals.ignoredShare * 100);
    if (signals.ignoredShare >= LIMITS.unreplied.high) {
      raise("high");
      reasons.push(
        `${percent}% of the ${signals.started7d} conversations this number started this week were never replied to. Being ignored at that rate is read as unwanted messaging.`
      );
    } else if (signals.ignoredShare >= LIMITS.unreplied.watch) {
      raise("watch");
      reasons.push(
        `${percent}% of the ${signals.started7d} conversations started this week got no reply.`
      );
    }
  }

  if (ageDays !== null && ageDays < LIMITS.youngDays && signals.newContacts24h >= LIMITS.youngNewContacts) {
    raise("high");
    reasons.push(
      `Nothing on this number is older than ${ageDays < 1 ? "today" : `${Math.floor(ageDays)} day(s)`}, and it is already starting conversations. New numbers are the ones WhatsApp bans fastest.`
    );
  }

  return { level, reasons };
}

// GET /api/risk — one entry per phone this caller may see.
router.get("/", async (req, res, next) => {
  try {
    const allowed = await visibleSessionIds(req.identity);
    const sessions = await store.listAllSessions();
    const mine = sessions.filter((s) => allowed === null || allowed.includes(Number(s.id)));

    const out = [];
    for (const session of mine) {
      const id = Number(session.id);
      const signals = await signalsFor(id);
      // From the oldest message on the number, not from when its QR was
      // scanned. A phone linked this morning carrying six months of
      // conversation is an old number, and telling its agent otherwise is how
      // this banner earns being ignored.
      const ageDays = signals.oldestMessage
        ? (Date.now() - new Date(signals.oldestMessage).getTime()) / 86_400_000
        : null;
      const { level, reasons } = assess(signals, ageDays);

      out.push({
        session_id: id,
        label: session.label || "",
        phone_number: store.visibleNumber(session),
        level,
        reasons,
        signals,
      });
    }

    res.json(out);
  } catch (err) {
    next(err);
  }
});

export default router;
