/**
 * One pool, one query helper.
 *
 * Deliberately thin: raw SQL against a schema that is already written down in
 * db/001_init.sql, rather than a second description of the same tables in an
 * ORM. The schema is the contract three people are building against, and it
 * should be readable in one file.
 */

import pg from "pg";
import { config } from "./config.js";

export const pool = new pg.Pool({ connectionString: config.databaseUrl, max: 10 });

/** Runs a query and returns the rows. */
export async function q(text, params = []) {
  const result = await pool.query(text, params);
  return result.rows;
}

/** Runs a query expected to match at most one row. */
export async function one(text, params = []) {
  const rows = await q(text, params);
  return rows[0] || null;
}

/** Runs `fn` inside a transaction, rolling back if it throws. */
export async function tx(fn) {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
