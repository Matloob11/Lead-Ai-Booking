/**
 * Webhook Forwarding to Django Backend / Gateway
 */

import { config } from "../config.js";
import { envelope } from "../inbound/normalise.js";
import { q, one } from "../db.js";

export async function emitWebhook(eventRowId, metaPayload, phoneNumber) {
  if (!config.webhookUrl) return false;

  const body = envelope(metaPayload, phoneNumber);
  const headers = {
    "Content-Type": "application/json",
  };
  if (config.webhookToken) {
    headers["Authorization"] = `Bearer ${config.webhookToken}`;
  }

  try {
    const res = await fetch(config.webhookUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });

    if (res.ok) {
      await q(`UPDATE qr_event SET status = 'processed', forwarded_at = now() WHERE id = $1`, [
        eventRowId,
      ]);
      return true;
    } else {
      console.warn(
        `[wa-qr] webhook delivery failed for event #${eventRowId}: HTTP ${res.status}`
      );
      return false;
    }
  } catch (err) {
    console.error(`[wa-qr] webhook delivery error for event #${eventRowId}:`, err.message);
    return false;
  }
}

export async function retryPendingWebhooks() {
  if (!config.webhookUrl) return;

  const pendingEvents = await q(
    `SELECT e.*, s.phone_number
     FROM qr_event e
     LEFT JOIN qr_session s ON e.session_id = s.id
     WHERE e.forwarded_at IS NULL AND e.status = 'processed'
     ORDER BY e.id ASC
     LIMIT 50`
  );

  for (const event of pendingEvents) {
    if (event.payload) {
      await emitWebhook(event.id, event.payload, event.phone_number);
    }
  }
}
