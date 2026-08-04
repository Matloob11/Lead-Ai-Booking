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

/**
 * One sentence an agent can act on, from whatever the library threw.
 *
 * `last_error` is printed in full on the phone's card, because it is the only
 * explanation of why a number stopped working. That is right when the error is
 * a sentence and wrong when it is Chromium's launch failure: forty lines of
 * stack trace, a Puppeteer troubleshooting URL and two copies of the same
 * message, filling the card and burying the one fact worth having.
 *
 * The whole thing still goes to the log. Only what the screen shows is cut.
 */
function readableError(error) {
  const text = String(error?.message || error || "").trim();
  if (!text) return "";

  if (/profile appears to be in use|SingletonLock/i.test(text)) {
    return (
      "The browser could not start: a previous run left this phone's profile " +
      "locked. Restarting the service clears it."
    );
  }
  if (/Failed to launch the browser process/i.test(text)) {
    return "The browser this phone runs inside could not start. See the service log.";
  }
  if (/Execution context was destroyed|Target closed|Session closed/i.test(text)) {
    return "The connection to WhatsApp Web was lost.";
  }

  // Anything else: its first line, which is where a real message lives.
  const first = text.split("\n")[0].trim();
  return first.length > 200 ? `${first.slice(0, 197)}…` : first;
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
    // What the history import is doing, so the panel can say so rather than
    // looking finished while it is still reading months off the handset.
    history: {
      status: row.history_status || "pending",
      error: row.history_error || "",
      chatsDone: Number(row.history_chats_done || 0),
      chatsTotal: Number(row.history_chats_total || 0),
      messages: Number(row.history_messages || 0),
      // Both ends of the run. The panel needs the start to say how much longer
      // this will take, and "12 of 84" without that is a number somebody has to
      // watch for a while before it means anything.
      startedAt: row.history_started_at || null,
      finishedAt: row.history_finished_at || null,
    },
  };
}

/** The three files Chromium uses to claim a profile for itself. */
const PROFILE_LOCKS = ["SingletonLock", "SingletonSocket", "SingletonCookie"];

/**
 * Throws away profile locks left behind by the container this one replaced.
 *
 * Chromium claims a profile with these three files and releases them when it
 * shuts down. It never gets to shut down here: rebuilding the image recreates
 * the container, which kills the process, and the claim survives on the mounted
 * volume. The next start then refuses every profile — "the profile appears to
 * be in use by another Chromium process on another computer" — and every linked
 * phone sits disconnected with a page of stack trace where its status should
 * be. That happened after every single rebuild today.
 *
 * Safe precisely because of when it runs: this process has just started and has
 * not launched a browser yet, so nothing of ours holds a profile and any claim
 * on disk is by definition stale. Only the three lock files go — the session
 * data beside them is what saves every phone from scanning again.
 */
async function clearStaleProfileLocks() {
  let entries = [];
  try {
    entries = await fs.readdir(authRoot, { withFileTypes: true });
  } catch {
    return; // nothing linked yet
  }

  let cleared = 0;
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    for (const name of PROFILE_LOCKS) {
      const target = path.join(authRoot, entry.name, name);
      // `rm` and not `unlink`: SingletonSocket is a symlink, and on a volume
      // written by a container that no longer exists it may dangle.
      const gone = await fs
        .rm(target, { force: true })
        .then(() => true)
        .catch(() => false);
      if (gone) cleared += 1;
    }
  }

  if (cleared) {
    console.info(`[wa-qr] cleared ${cleared} stale Chromium profile lock(s) from the last run`);
  }
}

/** Restores all existing sessions from DB on startup (except banned ones). */
export async function restoreSessions() {
  // Before any client is built, or the first one to start takes the lock error
  // and the rest queue up behind it.
  await clearStaleProfileLocks();

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

/**
 * Unlinks the phone and keeps every word it ever carried.
 *
 * This used to delete the session row, and the row is what conversations hang
 * off — so disconnecting a phone took its whole history down by cascade. That
 * is the exact outcome importing the history exists to prevent: an agent who
 * wanted a customer off the books only had to press Disconnect.
 *
 * So the phone is logged out, its credentials are thrown away, and the row
 * stays exactly where it is. Scanning again on the same row picks the same
 * conversations back up and reads only what was missed.
 */
export async function disconnectSession(id) {
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
  await store.updateSession(sessionId, {
    status: "disconnected",
    qr_data_url: "",
    last_error: "Disconnected by an administrator. Scan the QR again to relink — the chats are kept.",
    last_seen_at: new Date(),
  });

  emit("status", { sessionId, status: "disconnected", error: "" });
  return formatSession(await store.getSessionById(sessionId));
}

/**
 * Starts a phone that is not connected, whatever is standing in its way.
 *
 * Two things end up here. A deliberate disconnect cancels the reconnect timer —
 * it has to, or the service would simply undo it — so nothing was left to
 * produce a code when somebody wanted the phone back, and "Show QR" waited for
 * one that was never going to be generated.
 *
 * The other is a client that has a live Chromium and is still not working: a
 * session can sit at 'authenticated' indefinitely when WhatsApp Web's own load
 * stalls, and one did, for twenty minutes, with no way out of it from the
 * panel. So a client that exists is not taken as a client that is doing
 * anything — only 'ready' is. Anything else is thrown away and started again,
 * which is exactly what the operator would otherwise be restarting the whole
 * service to achieve.
 */
export async function relinkSession(id) {
  const sessionId = Number(id);
  const row = await store.getSessionById(sessionId);
  if (!row) return null;
  if (row.status === "banned") {
    throw new Error("This number was refused and cannot be linked here.");
  }
  if (row.status === "ready" && clients.has(sessionId)) return formatSession(row);

  cancelReconnect(sessionId);
  await store.updateSession(sessionId, { status: "initialising", last_error: "" });

  // initClient destroys whatever is already there before it starts.
  initClient(sessionId).catch((err) => {
    console.error(`[wa-qr] failed to relink session #${sessionId}:`, err);
  });

  return formatSession(await store.getSessionById(sessionId));
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
    // Not a downgrade. This fires again whenever WhatsApp re-authenticates a
    // link that is already working, and writing 'authenticated' over 'ready'
    // made a phone that was busy importing look like one that had never
    // finished connecting — for hours, with the panel saying the import was
    // paused while it was in fact running.
    const current = await store.getSessionById(sessionId);
    if (current?.status === "ready") {
      await store.updateSession(sessionId, { last_seen_at: new Date() });
      return;
    }

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

    // The same number, arriving on a second row.
    //
    // "Link a phone" always opens a fresh row, so scanning a number that is
    // already known leaves its months of conversation on the old one and starts
    // an empty one beside it. Neither half is the whole chat. The old row's
    // contents are moved onto this one — which is the row holding the live
    // credentials — and the emptied row goes.
    //
    // It also has to happen before the number is written here at all:
    // qr_session.phone_number is unique, and the old row is still holding it.
    const twin = await store.getSessionByPhoneNumber(phoneDigits);
    if (twin && Number(twin.id) !== sessionId) {
      console.info(
        `[wa-qr] ${phoneDigits} is already known as session #${twin.id} — ` +
          `moving its chats onto #${sessionId}`
      );
      await store.adoptHistoryFrom(twin.id, sessionId);
      await clearAuthData(Number(twin.id));
      cancelReconnect(Number(twin.id));
      clients.delete(Number(twin.id));
    }

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

    const errorMsg = readableError(reason) || "Disconnected";
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
    // The whole thing to the log, one sentence to the screen. This is where
    // Chromium's launch failure arrives, and it is forty lines long.
    console.error(`[wa-qr] client initialization error for #${sessionId}:`, err);
    const errorMsg = readableError(err);
    await store.updateSession(sessionId, {
      status: "disconnected",
      last_error: errorMsg,
    });
    emit("status", { sessionId, status: "disconnected", error: errorMsg });
    scheduleReconnect(sessionId);
  }
}

/* --------------------------------------------------------------- watchdog */

/** How often every live phone is asked whether it is still there. */
const HEALTH_EVERY_MS = 120_000;

/** And how long it gets to answer before the answer is taken as "no". */
const HEALTH_TIMEOUT_MS = 20_000;

let healthTimer = null;

/**
 * Notices a phone that has died without saying so.
 *
 * WhatsApp Web runs inside a real browser, and a browser can crash. When it
 * does, whatsapp-web.js does not always find out: the page aborted with
 * "No EM_ASM constant found" and "Protocol error: Target closed", no
 * `disconnected` event was emitted, nothing was scheduled to reconnect, and the
 * session sat at its last known status for three hours and seventeen minutes.
 * Everything downstream believed it — the panel drew it as connected, and the
 * history import waited on a call that was never going to return.
 *
 * So the question gets asked out loud instead of assumed. `getState()` is
 * itself a page evaluation, so it is given a deadline: a client that cannot say
 * how it is within twenty seconds is not well, whatever the reason.
 */
export function startHealthWatch() {
  if (healthTimer) return;

  healthTimer = setInterval(async () => {
    for (const [sessionId, client] of [...clients.entries()]) {
      let state = null;
      try {
        state = await Promise.race([
          client.getState(),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error("getState timed out")), HEALTH_TIMEOUT_MS)
          ),
        ]);
      } catch (err) {
        state = null;
        console.warn(`[wa-qr] health check for #${sessionId} failed: ${err.message}`);
      }

      if (state === "CONNECTED") {
        await store.updateSession(sessionId, { last_seen_at: new Date() }).catch(() => {});
        continue;
      }

      const row = await store.getSessionById(sessionId).catch(() => null);
      if (!row || row.status === "banned") continue;

      console.warn(
        `[wa-qr] #${sessionId} is not answering (state ${state ?? "unknown"}) — restarting it`
      );
      await store
        .updateSession(sessionId, {
          status: "disconnected",
          last_error: "The connection to WhatsApp stopped responding and is being restarted.",
        })
        .catch(() => {});
      emit("status", { sessionId, status: "disconnected", error: "" });

      // Straight to a fresh client rather than a backoff: this is not a phone
      // that went away, it is a browser that died, and the only fix is a new
      // one. The stored credentials are untouched, so it comes back on its own.
      clients.delete(sessionId);
      try {
        await client.destroy();
      } catch {}
      initClient(sessionId).catch((err) =>
        console.error(`[wa-qr] could not restart #${sessionId}:`, err)
      );
    }
  }, HEALTH_EVERY_MS);

  console.info("[wa-qr] health watch active");
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
