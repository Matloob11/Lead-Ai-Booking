/**
 * whatsapp-web.js Session Lifecycle Manager
 */

import fs from "node:fs/promises";
import path from "node:path";
import QRCode from "qrcode";
import pkg from "whatsapp-web.js";
const { Client, LocalAuth } = pkg;

import { authRoot, guardNumber } from "../config.js";
import * as store from "./store.js";

const clients = new Map(); // sessionId -> Client instance
const reconnectTimers = new Map(); // sessionId -> setTimeout
const reconnectAttempts = new Map(); // sessionId -> count
const eventHandlers = new Set();

/** Register event handler for Agent 2. */
export function onEvent(handler) {
  eventHandlers.add(handler);
  return () => eventHandlers.delete(handler);
}

/** Gets live client instance by session ID. */
export function getClient(id) {
  return clients.get(Number(id)) || null;
}

function emit(type, payload) {
  for (const handler of eventHandlers) {
    try {
      // A handler is free to be async, and a rejected promise from one of them
      // must not become an unhandled rejection that takes the process down.
      Promise.resolve(handler(type, payload)).catch((err) =>
        console.error(`[wa-qr] event handler rejected for ${type}:`, err)
      );
    } catch (err) {
      console.error(`[wa-qr] event handler error for ${type}:`, err);
    }
  }
}

function formatSession(row) {
  if (!row) return null;
  return {
    id: Number(row.id),
    phoneNumber: store.visibleNumber(row),
    label: row.label || "",
    status: row.status || "initialising",
    qrDataUrl: row.qr_data_url || "",
    lastError: row.last_error || "",
    lastSeenAt: row.last_seen_at || null,
    createdAt: row.created_at || null,
  };
}

/** Restores all existing sessions from DB on startup (except banned ones). */
export async function restoreSessions() {
  const allSessions = await store.listAllSessions();
  const activeSessions = allSessions.filter((s) => s.status !== "banned");

  console.info(`[wa-qr] restoring ${activeSessions.length} session(s)...`);
  for (const row of activeSessions) {
    const sessionId = Number(row.id);

    // The guard runs again here, not only on `ready`. A number linked when the
    // blocklist was shorter would otherwise reconnect on every restart and
    // stay connected until `ready` fired — the window this check exists to
    // close. Refusing before Chromium starts means it never connects at all.
    const linked = store.visibleNumber(row);
    if (linked) {
      try {
        guardNumber(linked);
      } catch (err) {
        console.error(
          `[wa-qr] REFUSING to restore session #${sessionId}: ${linked} is on the Business Platform`
        );
        await refuseNumber(sessionId, null, linked, err.message);
        continue;
      }
    }

    initClient(sessionId).catch((err) => {
      console.error(`[wa-qr] failed to restore session #${sessionId}:`, err);
    });
  }
}

/** Creates a new session and starts QR generation. */
export async function createSession({ label = "" } = {}) {
  const row = await store.createSessionRecord({ label });
  const sessionId = Number(row.id);

  initClient(sessionId).catch((err) => {
    console.error(`[wa-qr] failed to init session #${sessionId}:`, err);
  });

  return formatSession(row);
}

/** Gets a formatted session object by ID. */
export async function getSession(id) {
  const row = await store.getSessionById(id);
  return formatSession(row);
}

/** Lists all formatted session objects. */
export async function listSessions() {
  const rows = await store.listAllSessions();
  return rows.map(formatSession);
}

/** Destroys a session, logs out, deletes auth files and DB record. */
export async function destroySession(id) {
  const sessionId = Number(id);

  cancelReconnect(sessionId);

  const client = clients.get(sessionId);
  if (client) {
    clients.delete(sessionId);
    try {
      await client.logout();
    } catch {}
    try {
      await client.destroy();
    } catch {}
  }

  await clearAuthData(sessionId);
  await store.deleteSessionRecord(sessionId);
  emit("status", { sessionId, status: "disconnected", error: "Session destroyed" });
}

/** Every place a session's auth data is thrown away. */
async function clearAuthData(sessionId) {
  // LocalAuth stores under `<dataPath>/session-<clientId>`, and the clientId is
  // itself `session-<id>`; the second path covers a differently-prefixed
  // directory left behind by an older run.
  const paths = [
    path.join(authRoot, `session-session-${sessionId}`),
    path.join(authRoot, `session-${sessionId}`),
  ];
  for (const p of paths) {
    await fs.rm(p, { recursive: true, force: true }).catch(() => {});
  }
}

/** Stops all reconnect work for a session. */
function cancelReconnect(sessionId) {
  if (reconnectTimers.has(sessionId)) {
    clearTimeout(reconnectTimers.get(sessionId));
    reconnectTimers.delete(sessionId);
  }
  reconnectAttempts.delete(sessionId);
}

/**
 * Cuts a refused number loose and makes sure it cannot come back.
 *
 * Called when guardNumber rejects a number — either at `ready`, or at restore
 * for one linked before the blocklist grew. Logging out, wiping the auth data
 * and recording 'banned' together are what stop the next restart from
 * reconnecting it: the status is what restoreSessions filters on, and without
 * the wipe the stored credentials would still be valid.
 */
async function refuseNumber(sessionId, client, phoneNumber, errorMessage) {
  cancelReconnect(sessionId);
  clients.delete(sessionId);

  if (client) {
    try {
      await client.logout();
    } catch {}
    try {
      await client.destroy();
    } catch {}
  }

  await clearAuthData(sessionId);

  await store.updateSession(sessionId, {
    status: "banned",
    phone_number: phoneNumber || "",
    qr_data_url: "",
    last_error: errorMessage,
    last_seen_at: new Date(),
  });

  emit("status", { sessionId, status: "banned", error: errorMessage });
}

/** Initializes whatsapp-web.js Client instance for a session. */
async function initClient(sessionId) {
  if (clients.has(sessionId)) {
    const existing = clients.get(sessionId);
    try {
      await existing.destroy();
    } catch {}
    clients.delete(sessionId);
  }

  const client = new Client({
    authStrategy: new LocalAuth({
      clientId: `session-${sessionId}`,
      dataPath: authRoot,
    }),
    puppeteer: {
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: ["--disable-dev-shm-usage"],
    },
  });

  clients.set(sessionId, client);

  client.on("qr", async (qrStr) => {
    try {
      const qrDataUrl = await QRCode.toDataURL(qrStr);
      await store.updateSession(sessionId, {
        status: "qr",
        qr_data_url: qrDataUrl,
        last_seen_at: new Date(),
      });
      emit("status", { sessionId, status: "qr", error: "" });
    } catch (err) {
      console.error(`[wa-qr] QR generation failed for session #${sessionId}:`, err);
    }
  });

  client.on("authenticated", async () => {
    await store.updateSession(sessionId, {
      status: "authenticated",
      qr_data_url: "",
      last_seen_at: new Date(),
    });
    emit("status", { sessionId, status: "authenticated", error: "" });
  });

  client.on("ready", async () => {
    const rawNumber = client.info?.wid?.user || client.info?.me?.user || "";
    const phoneDigits = String(rawNumber).replace(/\D/g, "");

    // CRITICAL SECURITY CHECK: Guard against Business Platform numbers
    try {
      guardNumber(phoneDigits);
    } catch (err) {
      console.error(
        `[wa-qr] CRITICAL REFUSAL: Session #${sessionId} linked number ${phoneDigits} is BLOCKED!`
      );
      await refuseNumber(sessionId, client, phoneDigits, err.message);
      return;
    }

    reconnectAttempts.delete(sessionId);

    await store.updateSession(sessionId, {
      status: "ready",
      phone_number: phoneDigits,
      qr_data_url: "",
      last_error: "",
      last_seen_at: new Date(),
    });

    emit("status", { sessionId, status: "ready", error: "" });
  });

  client.on("disconnected", async (reason) => {
    const current = await store.getSessionById(sessionId);
    if (current?.status === "banned") return;

    const errorMsg = String(reason || "Disconnected");
    await store.updateSession(sessionId, {
      status: "disconnected",
      last_error: errorMsg,
      last_seen_at: new Date(),
    });

    emit("status", { sessionId, status: "disconnected", error: errorMsg });
    scheduleReconnect(sessionId);
  });

  client.on("auth_failure", async (msg) => {
    const errorMsg = String(msg || "Auth failure");

    // Stored credentials that no longer authenticate will never start working
    // again, and reconnecting with them just fails the same way. Throwing them
    // away is what lets the next attempt fall back to a fresh QR — otherwise
    // the session sits at 'disconnected' for good and the only way out is to
    // delete it by hand.
    await clearAuthData(sessionId);

    await store.updateSession(sessionId, {
      status: "disconnected",
      last_error: `${errorMsg} — the link was dropped, scan the QR again`,
    });

    emit("status", { sessionId, status: "disconnected", error: errorMsg });
    scheduleReconnect(sessionId);
  });

  client.on("change_state", async () => {
    await store.updateSession(sessionId, {
      last_seen_at: new Date(),
    });
  });

  // RAW library objects for Agent 2 — normalising them is that side's job.
  //
  // `message_create`, not `message`: the latter only fires for incoming ones.
  // On a QR-linked phone the agent replies from the handset as often as from
  // the panel, and those replies have to reach the thread too or the history
  // is half a conversation. The raw object carries `fromMe`, which is what
  // tells the two apart downstream.
  client.on("message_create", (message) => {
    emit("message", { sessionId, message });
  });

  client.on("message_reaction", (reaction) => {
    emit("reaction", { sessionId, reaction });
  });

  client.on("message_ack", (message, ack) => {
    emit("ack", { sessionId, message, ack });
  });

  try {
    await client.initialize();

    // WhatsApp Web's own errors, which until now went nowhere.
    //
    // Everything this service does inside the browser is a page evaluation,
    // and when WhatsApp's script throws, the evaluation comes back undefined
    // with the reason left on a console we were not reading. That is how a
    // send could fail with nothing anywhere to say why.
    client.pupPage?.on("pageerror", (err) => {
      console.warn(`[wa-qr] WhatsApp page error (#${sessionId}): ${err.message}`);
    });
    client.pupPage?.on("console", async (msg) => {
      if (msg.type() !== "error") return;
      // The interesting half of a WhatsApp error is an object, and printing
      // the console text alone renders it "[object Object]".
      const parts = await Promise.all(
        msg.args().map((a) => a.jsonValue().catch(() => null))
      ).catch(() => []);
      const detail = parts.filter(Boolean).map((p) => JSON.stringify(p)).join(" ");
      console.warn(
        `[wa-qr] WhatsApp console (#${sessionId}): ${msg.text().slice(0, 200)} ${detail.slice(0, 400)}`
      );
    });

    // Which request WhatsApp's server refused, and with what.
    client.pupPage?.on("response", async (res) => {
      if (res.status() < 400) return;
      console.warn(`[wa-qr] WhatsApp HTTP ${res.status()} (#${sessionId}) ${res.url().slice(0, 160)}`);
    });
  } catch (err) {
    console.error(`[wa-qr] client initialization error for #${sessionId}:`, err);
    await store.updateSession(sessionId, {
      status: "disconnected",
      last_error: err.message,
    });
    emit("status", { sessionId, status: "disconnected", error: err.message });
  }
}

/** Schedules exponential backoff reconnect attempt. */
function scheduleReconnect(sessionId) {
  if (reconnectTimers.has(sessionId)) return;

  const attempt = (reconnectAttempts.get(sessionId) || 0) + 1;
  reconnectAttempts.set(sessionId, attempt);

  // Exponential backoff: 5s, 10s, 20s, 40s, 80s, 160s, max 300s (5m)
  const delayMs = Math.min(300000, 5000 * Math.pow(2, attempt - 1));

  console.info(
    `[wa-qr] scheduling reconnect attempt #${attempt} for session #${sessionId} in ${delayMs / 1000}s`
  );

  const timer = setTimeout(async () => {
    reconnectTimers.delete(sessionId);
    const session = await store.getSessionById(sessionId);
    if (!session || session.status === "banned") return;

    try {
      await initClient(sessionId);
    } catch (err) {
      console.error(`[wa-qr] reconnect failed for #${sessionId}:`, err);
    }
  }, delayMs);

  reconnectTimers.set(sessionId, timer);
}
