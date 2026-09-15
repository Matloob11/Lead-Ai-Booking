const Database = require('better-sqlite3');

const SESSION_ID = 'e209881a-0aa3-4463-849f-ff0ed37144b5';
const EXPECTED_MESSAGES = 675;
const dbPath = process.argv[2];

if (!dbPath) throw new Error('database path is required');

const db = new Database(dbPath, { fileMustExist: true });
try {
  db.pragma('busy_timeout = 10000');
  db.pragma('foreign_keys = ON');

  db.transaction(() => {
    const row = db.prepare('SELECT id, name, status, config FROM sessions WHERE id = ?').get(SESSION_ID);
    if (!row || row.id !== SESSION_ID || row.name !== 'asma' || row.status !== 'disconnected') {
      throw new Error('restored Asma identity/status guard failed');
    }
    const { count } = db.prepare('SELECT COUNT(*) AS count FROM messages WHERE sessionId = ?').get(SESSION_ID);
    if (count !== EXPECTED_MESSAGES) throw new Error('restored Asma message-count guard failed');

    let config = {};
    if (typeof row.config === 'string' && row.config.trim()) {
      config = JSON.parse(row.config);
    }
    if (!config || typeof config !== 'object' || Array.isArray(config)) {
      throw new Error('restored Asma config guard failed');
    }
    config.manualStartRequired = true;
    const result = db.prepare('UPDATE sessions SET config = ? WHERE id = ? AND name = ?').run(
      JSON.stringify(config),
      SESSION_ID,
      'asma',
    );
    if (result.changes !== 1) throw new Error('restored Asma manual-start update failed');
  })();

  const verified = db
    .prepare(
      `SELECT COUNT(*) AS count
       FROM sessions
       WHERE id = ? AND name = 'asma' AND status = 'disconnected'
         AND json_extract(config, '$.manualStartRequired') = 1`,
    )
    .get(SESSION_ID);
  if (verified.count !== 1) throw new Error('restored Asma manual-start verification failed');
  console.log('restored-asma-manual-start=PASS');
  console.log(`restored-message-count=${EXPECTED_MESSAGES}`);
} finally {
  db.close();
}
