/**
 * Applies every .sql file in db/ once, in name order.
 *
 * A migration that has run is recorded, so restarting the container does not
 * try to build a table over itself — the same guarantee Django's
 * django_migrations gives, in the smallest form that provides it.
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pool } from "../db.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const sqlDir = path.resolve(here, "..", "..", "db");

export async function migrate() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS qr_migration (
      name       TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )`);

  const applied = new Set(
    (await pool.query("SELECT name FROM qr_migration")).rows.map((r) => r.name)
  );

  const files = (await fs.readdir(sqlDir)).filter((f) => f.endsWith(".sql")).sort();
  for (const file of files) {
    if (applied.has(file)) continue;
    const sql = await fs.readFile(path.join(sqlDir, file), "utf8");
    await pool.query("BEGIN");
    try {
      await pool.query(sql);
      await pool.query("INSERT INTO qr_migration (name) VALUES ($1)", [file]);
      await pool.query("COMMIT");
      console.info(`[wa-qr] applied ${file}`);
    } catch (error) {
      await pool.query("ROLLBACK");
      throw error;
    }
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  migrate()
    .then(() => process.exit(0))
    .catch((error) => {
      console.error(error);
      process.exit(1);
    });
}
