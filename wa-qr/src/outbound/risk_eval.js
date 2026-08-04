import { q } from "../db.js";

const LIMITS = {
  newContacts: { watch: 15, high: 30 },
  outbound: { watch: 150, high: 300 },
  unreplied: { watch: 0.4, high: 0.6, minStarted: 20 },
  youngDays: 3,
  youngNewContacts: 10,
};

export async function getSessionRisk(sessionId) {
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
  const signals = {
    outbound24h: Number(r.outbound_24h || 0),
    failed24h: Number(r.failed_24h || 0),
    newContacts24h: Number(r.new_contacts_24h || 0),
    started7d: started,
    ignored7d: Number(r.ignored_7d || 0),
    ignoredShare: started ? Number(r.ignored_7d || 0) / started : 0,
    oldestMessage: r.oldest_message || null,
  };

  const ageDays = signals.oldestMessage
    ? (Date.now() - new Date(signals.oldestMessage).getTime()) / 86_400_000
    : null;

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

  if (
    ageDays !== null &&
    ageDays < LIMITS.youngDays &&
    signals.newContacts24h >= LIMITS.youngNewContacts
  ) {
    raise("high");
    reasons.push(
      `Nothing on this number is older than ${
        ageDays < 1 ? "today" : `${Math.floor(ageDays)} day(s)`
      }, and it is already starting conversations. New numbers are the ones WhatsApp bans fastest.`
    );
  }

  return { level, reasons, signals };
}
