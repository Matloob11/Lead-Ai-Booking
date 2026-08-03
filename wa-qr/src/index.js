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

  // Each of these is a separate piece of work; see the handover notes. Until
  // they land, the service starts, migrates and serves nothing, which is a
  // truthful state to be in rather than a crash.
  const { startApi } = await import("./api/server.js").catch(() => ({}));
  const { restoreSessions } = await import("./sessions/manager.js").catch(() => ({}));

  if (restoreSessions) {
    await restoreSessions();
  } else {
    console.warn("[wa-qr] sessions/manager.js not built yet — no phone will connect");
  }

  if (startApi) {
    startApi(config.port);
  } else {
    console.warn("[wa-qr] api/server.js not built yet — nothing is being served");
  }
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
