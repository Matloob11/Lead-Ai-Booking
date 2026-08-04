/**
 * Handing an event on to the Django backend.
 *
 * The body is `envelope(value)` — the same entry/changes wrapper Meta puts
 * around a callback — so the receiver is `apps/gateway/tasks.py` unchanged, and
 * no second parser exists to drift from the first.
 *
 * Nothing is sent until WEBHOOK_URL is set, which it deliberately is not yet;
 * see README, "Joining it up". Until then every event is still stored, and
 * `forwarded_at` stays null to say so.
 */

import { config } from "../config.js";
import { envelope } from "../inbound/normalise.js";
import { q } from "../db.js";

/**
 * How long to wait before trying again, in order.
 *
 * Short enough to ride out a restart or a deploy, and then it stops. A queue
 * that retries for ever eventually replays a day-old message into a live chat,
 * which is worse than not delivering it: the row is still on disk with
 * `forwarded_at` null, so a deliberate replay can pick it up.
 */
const RETRY_DELAYS_MS = [30_000, 120_000, 600_000];

/**
 * Give up on a POST that has not answered in this long.
 *
 * `fetch` has no timeout of its own, and this is awaited inside
 * `inbound/persist.js` — so a backend that accepts the connection and then
 * hangs would stall the handling of every message behind it.
 */
const REQUEST_TIMEOUT_MS = 15_000;

/** Retries waiting to fire, so shutdown (and tests) can stop them. */
const scheduled = new Map();

/**
 * Sends one event, and keeps trying for a while if that fails.
 *
 * Resolves as soon as the first attempt is done — a retry runs on its own and
 * the caller is not made to wait on it.
 *
 * @returns {Promise<boolean>} whether it was delivered on the first attempt
 */
export async function emitWebhook(eventRowId, metaPayload, phoneNumber) {
  if (!config.webhookUrl) return false;

  cancelRetry(eventRowId);
  return attempt(eventRowId, metaPayload, phoneNumber, 0);
}

/** Stops every pending retry. For a clean shutdown, and for tests. */
export function stopWebhookRetries() {
  for (const timer of scheduled.values()) clearTimeout(timer);
  scheduled.clear();
}

function cancelRetry(eventRowId) {
  const timer = scheduled.get(eventRowId);
  if (timer) {
    clearTimeout(timer);
    scheduled.delete(eventRowId);
  }
}

async function attempt(eventRowId, metaPayload, phoneNumber, index) {
  let failure = "";

  try {
    const headers = { "Content-Type": "application/json" };
    if (config.webhookToken) {
      headers.Authorization = `Bearer ${config.webhookToken}`;
    }

    const response = await fetch(config.webhookUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(envelope(metaPayload, phoneNumber)),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (response.ok) {
      // Only `forwarded_at` is written here. `status` belongs to whoever parsed
      // the event — it was processed either way, and saying otherwise because
      // the network failed would misreport what is actually on disk.
      await q(`UPDATE qr_event SET forwarded_at = now(), error = '' WHERE id = $1`, [eventRowId]);
      scheduled.delete(eventRowId);
      return true;
    }

    failure = `HTTP ${response.status}`;
  } catch (error) {
    failure = error.name === "TimeoutError" ? `no answer in ${REQUEST_TIMEOUT_MS / 1000}s` : error.message;
  }

  await recordFailure(eventRowId, failure, index);

  const delay = RETRY_DELAYS_MS[index];
  if (delay === undefined) {
    console.error(
      `[wa-qr] event #${eventRowId} was not delivered and will not be retried again: ${failure}`
    );
    scheduled.delete(eventRowId);
    return false;
  }

  console.warn(
    `[wa-qr] event #${eventRowId} delivery failed (${failure}); retrying in ${delay / 1000}s`
  );
  const timer = setTimeout(() => {
    scheduled.delete(eventRowId);
    attempt(eventRowId, metaPayload, phoneNumber, index + 1).catch((error) =>
      console.error(`[wa-qr] retry for event #${eventRowId} threw:`, error)
    );
  }, delay);
  scheduled.set(eventRowId, timer);

  return false;
}

/** Leaves why it failed on the row. `forwarded_at` stays null, which is the flag. */
async function recordFailure(eventRowId, failure, index) {
  try {
    await q(`UPDATE qr_event SET error = $1 WHERE id = $2`, [
      `webhook attempt ${index + 1}: ${failure}`.slice(0, 500),
      eventRowId,
    ]);
  } catch (error) {
    // The database being unreachable too is not a reason to lose the retry.
    console.error(`[wa-qr] could not record the delivery failure for #${eventRowId}:`, error.message);
  }
}
