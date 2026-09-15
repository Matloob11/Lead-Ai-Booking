'use strict';

// Fixed, one-purpose recovery tool for the 2026-08-08 Asma session deletion.
// It never prints phone numbers, message bodies, chat ids, or message metadata.

const Database = require('better-sqlite3');

const OLD_ID = 'e209881a-0aa3-4463-849f-ff0ed37144b5';
const REPLACEMENT_ID = '1faa69b9-3409-494d-8c93-2df8a9eb4975';
const SESSION_NAME = 'asma';
const MIN_SOURCE_MESSAGES = 675;
// Floors from the 2026-08-08 pre-delete snapshot. Live traffic may grow these;
// restore must leave each name's id + exact pre-restore count unchanged.
const UNTOUCHED_MIN = new Map([
  ['marketting', 68],
  ['minahil', 62],
]);

function fail(message) {
  throw new Error(`RESTORE_ABORTED: ${message}`);
}

function quoteIdentifier(value) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function tableInfo(db, schema, table) {
  return db.prepare(`PRAGMA ${quoteIdentifier(schema)}.table_info(${quoteIdentifier(table)})`).all();
}

function assertSource(db, schema = 'main') {
  const session = db
    .prepare(`SELECT id, name FROM ${quoteIdentifier(schema)}.sessions WHERE id = ?`)
    .get(OLD_ID);
  if (!session || session.name !== SESSION_NAME) {
    fail('backup does not contain the expected Asma session row');
  }

  const sessionRows = db
    .prepare(`SELECT COUNT(*) AS count FROM ${quoteIdentifier(schema)}.sessions WHERE id = ?`)
    .get(OLD_ID).count;
  if (sessionRows !== 1) fail(`backup session-row count is ${sessionRows}, expected 1`);

  const messageCount = db
    .prepare(`SELECT COUNT(*) AS count FROM ${quoteIdentifier(schema)}.messages WHERE sessionId = ?`)
    .get(OLD_ID).count;
  if (messageCount < MIN_SOURCE_MESSAGES) {
    fail(`backup message count is ${messageCount}, below required ${MIN_SOURCE_MESSAGES}`);
  }

  return messageCount;
}

function snapshotUntouched(db, phase) {
  const snap = new Map();
  for (const [name, minimum] of UNTOUCHED_MIN) {
    const rows = db.prepare('SELECT id FROM sessions WHERE name = ?').all(name);
    if (rows.length !== 1) fail(`${phase}: ${name} session-row count is ${rows.length}, expected 1`);
    const count = db.prepare('SELECT COUNT(*) AS count FROM messages WHERE sessionId = ?').get(rows[0].id).count;
    if (count < minimum) {
      fail(`${phase}: ${name} message count is ${count}, below floor ${minimum}`);
    }
    snap.set(name, { id: rows[0].id, count });
  }
  return snap;
}

function assertUntouchedUnchanged(db, before, phase) {
  for (const [name, prev] of before) {
    const row = db.prepare('SELECT id FROM sessions WHERE name = ?').get(name);
    if (!row || row.id !== prev.id) {
      fail(`${phase}: ${name} session id changed or missing`);
    }
    const count = db.prepare('SELECT COUNT(*) AS count FROM messages WHERE sessionId = ?').get(row.id).count;
    if (count !== prev.count) {
      fail(`${phase}: ${name} message count changed ${prev.count} -> ${count}`);
    }
  }
}

/** @returns {'absent' | 'replacement'} */
function assertAsmaRestorable(db) {
  const rows = db.prepare('SELECT id, name FROM sessions WHERE name = ?').all(SESSION_NAME);
  if (rows.length === 0) return 'absent';
  if (rows.length !== 1) fail(`live Asma session-row count is ${rows.length}, expected 0 or 1`);
  const row = rows[0];
  if (row.id === OLD_ID) {
    fail('old Asma id is already present live; refuse to run restore twice');
  }
  if (row.id !== REPLACEMENT_ID) {
    fail(`live Asma id is unexpected; expected absent or approved replacement ${REPLACEMENT_ID}`);
  }
  const messages = db.prepare('SELECT COUNT(*) AS count FROM messages WHERE sessionId = ?').get(row.id).count;
  if (messages !== 0) fail(`replacement Asma has ${messages} messages, expected 0`);

  // Fresh replacement must not carry any other session-owned data. Refuse instead of
  // silently deleting something outside approved session-row replacement.
  for (const table of ['message_batches', 'webhooks', 'templates', 'baileys_stored_messages', 'automation_rules']) {
    const exists = db
      .prepare("SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = ?")
      .get(table).count;
    if (!exists) continue;
    const columns = tableInfo(db, 'main', table).map(column => column.name);
    if (!columns.includes('sessionId')) continue;
    const count = db
      .prepare(`SELECT COUNT(*) AS count FROM ${quoteIdentifier(table)} WHERE sessionId = ?`)
      .get(row.id).count;
    if (count !== 0) fail(`replacement Asma owns ${count} rows in ${table}, expected 0`);
  }
  return 'replacement';
}

function commonInsertColumns(db, table) {
  const sourceNames = new Set(tableInfo(db, 'backup', table).map(column => column.name));
  const liveColumns = tableInfo(db, 'main', table);
  if (!liveColumns.length || !sourceNames.size) fail(`missing ${table} schema in live DB or backup`);

  for (const column of liveColumns) {
    if (sourceNames.has(column.name) || column.pk || column.dflt_value != null || column.notnull === 0) continue;
    fail(`live ${table}.${column.name} is required but absent from backup schema`);
  }
  return liveColumns.map(column => column.name).filter(name => sourceNames.has(name));
}

function insertFromBackup(db, table, whereColumn, whereValue) {
  const columns = commonInsertColumns(db, table);
  const names = columns.map(quoteIdentifier).join(', ');
  return db
    .prepare(
      `INSERT INTO main.${quoteIdentifier(table)} (${names}) ` +
        `SELECT ${names} FROM backup.${quoteIdentifier(table)} WHERE ${quoteIdentifier(whereColumn)} = ?`,
    )
    .run(whereValue).changes;
}

function inspect(backupPath) {
  const db = new Database(backupPath, { readonly: true, fileMustExist: true });
  try {
    const messageCount = assertSource(db);
    console.log('backup-session-rows=1');
    console.log(`backup-message-rows=${messageCount}`);
    console.log(`minimum-required=${MIN_SOURCE_MESSAGES}`);
    console.log('inspection=PASS');
  } finally {
    db.close();
  }
}

function restore(livePath, backupPath) {
  const db = new Database(livePath, { fileMustExist: true });
  try {
    db.pragma('foreign_keys = ON');
    db.pragma('busy_timeout = 5000');
    db.prepare('ATTACH DATABASE ? AS backup').run(backupPath);
    const sourceMessages = assertSource(db, 'backup');

    const transaction = db.transaction(() => {
      const untouched = snapshotUntouched(db, 'before');
      const asmaMode = assertAsmaRestorable(db);
      const oldLiveRows = db.prepare('SELECT COUNT(*) AS count FROM sessions WHERE id = ?').get(OLD_ID).count;
      if (oldLiveRows !== 0) fail(`old Asma id already has ${oldLiveRows} live rows, expected 0`);

      if (asmaMode === 'replacement') {
        const removed = db
          .prepare('DELETE FROM sessions WHERE id = ? AND name = ?')
          .run(REPLACEMENT_ID, SESSION_NAME).changes;
        if (removed !== 1) fail(`replacement delete changed ${removed} rows, expected 1`);
      }

      const insertedSessions = insertFromBackup(db, 'sessions', 'id', OLD_ID);
      if (insertedSessions !== 1) fail(`session restore inserted ${insertedSessions} rows, expected 1`);

      const sessionColumns = new Set(tableInfo(db, 'main', 'sessions').map(column => column.name));
      const assignments = ['status = ?'];
      const values = ['disconnected'];
      for (const name of ['nodeId', 'claimedAt', 'leaseExpiresAt', 'historySyncToken']) {
        if (sessionColumns.has(name)) assignments.push(`${quoteIdentifier(name)} = NULL`);
      }
      if (sessionColumns.has('removedAt')) {
        assignments.push(`${quoteIdentifier('removedAt')} = NULL`);
      }
      if (sessionColumns.has('config')) {
        const raw = db.prepare('SELECT config FROM sessions WHERE id = ?').get(OLD_ID)?.config;
        let config = {};
        if (typeof raw === 'string' && raw.trim()) {
          try {
            config = JSON.parse(raw);
          } catch {
            fail('restored Asma config is not valid JSON');
          }
        }
        if (!config || typeof config !== 'object' || Array.isArray(config)) {
          fail('restored Asma config guard failed');
        }
        config.manualStartRequired = true;
        assignments.push(`${quoteIdentifier('config')} = ?`);
        values.push(JSON.stringify(config));
      }
      if (sessionColumns.has('updatedAt')) {
        assignments.push(`${quoteIdentifier('updatedAt')} = ?`);
        values.push(new Date().toISOString());
      }
      values.push(OLD_ID);
      db.prepare(`UPDATE sessions SET ${assignments.join(', ')} WHERE id = ?`).run(...values);

      const insertedMessages = insertFromBackup(db, 'messages', 'sessionId', OLD_ID);
      if (insertedMessages !== sourceMessages) {
        fail(`message restore inserted ${insertedMessages} rows, expected ${sourceMessages}`);
      }

      const restored = db.prepare('SELECT id, name, status FROM sessions WHERE id = ?').get(OLD_ID);
      if (!restored || restored.name !== SESSION_NAME || restored.status !== 'disconnected') {
        fail('restored session identity/status assertion failed');
      }
      const restoredMessages = db.prepare('SELECT COUNT(*) AS count FROM messages WHERE sessionId = ?').get(OLD_ID).count;
      if (restoredMessages !== sourceMessages) fail('restored message-count assertion failed');
      assertUntouchedUnchanged(db, untouched, 'after');

      const foreignKeyErrors = db.prepare('PRAGMA foreign_key_check').all();
      if (foreignKeyErrors.length) fail(`foreign-key check found ${foreignKeyErrors.length} errors`);
      return { restoredMessages, asmaMode, untouched };
    });

    const { restoredMessages, asmaMode, untouched } = transaction.immediate();
    console.log(`asma-pre-state=${asmaMode}`);
    if (asmaMode === 'replacement') console.log(`removed-replacement-id=${REPLACEMENT_ID}`);
    console.log(`restored-session-id=${OLD_ID}`);
    console.log(`restored-message-rows=${restoredMessages}`);
    console.log('restored-status=disconnected');
    console.log('restored-manual-start=true');
    for (const [name, prev] of untouched) {
      console.log(`${name}-message-rows=${prev.count}`);
    }
    console.log('restore=PASS');
  } finally {
    try {
      db.prepare('DETACH DATABASE backup').run();
    } catch {
      // No attachment exists when an earlier open/attach assertion failed.
    }
    db.close();
  }
}

function main(argv) {
  const [mode, livePath, backupPath] = argv;
  if (mode === 'inspect' && livePath && !backupPath) return inspect(livePath);
  if (mode === 'restore' && livePath && backupPath) return restore(livePath, backupPath);
  fail('usage is inspect <backup-db> or restore <live-db> <backup-db>');
}

if (require.main === module) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}

module.exports = { inspect, restore };
