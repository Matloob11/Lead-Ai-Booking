import { q } from "../db.js";

const DEFAULT_MAX_NEW_CONTACTS_PER_DAY = 40;
const lastSendMap = new Map();

/**
 * Reads MAX_NEW_CONTACTS_PER_DAY from env or falls back to default 40.
 */
export function getMaxNewContactsPerDay() {
  const envVal = process.env.MAX_NEW_CONTACTS_PER_DAY;
  if (envVal && !isNaN(Number(envVal))) {
    return Number(envVal);
  }
  return DEFAULT_MAX_NEW_CONTACTS_PER_DAY;
}

/**
 * Checks if a session has exceeded daily limit of newly initiated conversations.
 */
export async function assertNewContactLimit(sessionId) {
  const limit = getMaxNewContactsPerDay();
  const rows = await q(
    `WITH mine AS (
       SELECT m.id, m.conversation_id, m.direction, m.created_at
         FROM qr_message m
         JOIN qr_conversation c ON c.id = m.conversation_id
        WHERE c.session_id = $1
     ),
     opened AS (
       SELECT DISTINCT ON (conversation_id)
              conversation_id, direction, created_at
         FROM mine
        ORDER BY conversation_id, created_at, id
     )
     SELECT count(*) AS cnt
       FROM opened
      WHERE direction = 'out' AND created_at > now() - interval '24 hours'`,
    [sessionId]
  );

  const cnt = Number(rows[0]?.cnt || 0);
  if (cnt >= limit) {
    throw new Error(
      `Daily limit of ${limit} new contacts reached for session ${sessionId}. Outbound chat initiation is paused for 24h to prevent WhatsApp account ban.`
    );
  }
  return { cnt, limit };
}

/**
 * Below this, identical text is somebody agreeing with ten customers.
 *
 * "Ok", "Thank you", "Yes sir", "Noted" — an agent answering forty chats sends
 * each of those to ten different people in an hour without thinking, and
 * blocking them for it would have made the panel unusable within a morning.
 * What WhatsApp acts on is the same *pitch* going out repeatedly, and a pitch
 * is not four characters long.
 */
const BULK_MIN_LENGTH = 25;

/** How many different people may get the same words in an hour. */
const BULK_MAX_RECIPIENTS = 10;

/**
 * Refuses the same message going out to person after person.
 *
 * This is the fastest way to lose a number, and unlike the other two limits it
 * is about what is being said rather than how much.
 */
export async function assertBulkGuard(text) {
  const body = typeof text === "string" ? text.trim() : "";
  if (body.length < BULK_MIN_LENGTH) return;

  const rows = await q(
    `SELECT count(DISTINCT c.contact_id) AS cnt
       FROM qr_message m
       JOIN qr_conversation c ON c.id = m.conversation_id
      WHERE m.direction = 'out'
        AND m.body = $1
        AND m.created_at > now() - interval '1 hour'`,
    [body]
  );

  const cnt = Number(rows[0]?.cnt || 0);
  if (cnt >= BULK_MAX_RECIPIENTS) {
    throw new Error(
      `This exact message has already gone to ${cnt} different numbers in the past hour. ` +
        `Sending the same thing to person after person is the quickest way to have this ` +
        `number banned, so it is being stopped here.`
    );
  }
}

/**
 * Enforces an 8-15 second random waqfa between sends for chats initiated by us.
 */
export async function enforcePacingDelay(sessionId) {
  const lastTime = lastSendMap.get(sessionId) || 0;
  const now = Date.now();
  // Random delay between 8000ms (8s) and 15000ms (15s)
  const requiredDelay = 8000 + Math.floor(Math.random() * 7000);
  const elapsed = now - lastTime;

  if (elapsed < requiredDelay) {
    const waitMs = requiredDelay - elapsed;
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }

  lastSendMap.set(sessionId, Date.now());
}
