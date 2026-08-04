/**
 * Entry point.
 *
 * Deliberately small: it starts the database, brings back the sessions that
 * were linked before the last restart, and serves the API. The three pieces it
 * wires together are built separately and meet only here —
 *
 *   sessions/manager.js   the phone connections and their QR lifecycle
 *   inbound/persist.js    turning events into rows
 *   api/server.js         the REST surface and the panel
 *
 * so the file to read to understand the shape is this one, and the files to
 * read to understand the work are those.
 */

import fs from "node:fs/promises";

import { config, authRoot, mediaRoot } from "./config.js";
import { migrate } from "./db/migrate.js";
import { pool } from "./db.js";

async function main() {
  await fs.mkdir(authRoot, { recursive: true });
  await fs.mkdir(mediaRoot, { recursive: true });

  await migrate();
  console.info("[wa-qr] database ready");

  if (config.blockedNumbers.size) {
    console.info(
      `[wa-qr] ${config.blockedNumbers.size} number(s) are refused: they are live on ` +
        `the WhatsApp Business Platform and must not be linked by QR`
    );
  } else {
    console.warn(
      "[wa-qr] BLOCKED_NUMBERS is empty — nothing stops a verified Business " +
        "Platform number from being linked, and a ban on one cannot be undone"
    );
  }

  const { startApi } = await import("./api/server.js");
  const { restoreSessions, startHealthWatch } = await import("./sessions/manager.js");
  const { startPersistence } = await import("./inbound/persist.js");
  const { startHistoryImport } = await import("./inbound/backfill.js");

  // Before the sessions, not after: the manager emits into a set of handlers,
  // and an event that arrives with nothing subscribed is simply dropped. A
  // phone that reconnects during startup would otherwise deliver whatever it
  // had been holding into an empty room.
  startPersistence();

  // Same reason, and one more: this one subscribes to `ready`, which every
  // restored phone fires within seconds of restoreSessions() being called.
  startHistoryImport();

  await restoreSessions();

  // After the sessions, because it only has something to watch once there is
  // something running.
  startHealthWatch();

  startApi(config.port);
}

// A phone connection that dies takes its Chromium with it; without this the
// process would sit there holding a database pool and answering nothing.
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    console.info(`[wa-qr] ${signal} — shutting down`);
    await pool.end().catch(() => {});
    process.exit(0);
  });
}

main().catch((error) => {
  console.error("[wa-qr] failed to start:", error);
  process.exit(1);
});
