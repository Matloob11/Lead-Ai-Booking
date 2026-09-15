const Database = require('better-sqlite3');
const db = new Database(process.env.DATABASE_NAME || '/app/data/openwa.sqlite', { readonly: true });

const cols = db.prepare('PRAGMA table_info(chat_leads)').all().map(c => c.name);
console.log('cols=' + cols.join(','));

const count = db.prepare("SELECT COUNT(*) AS n FROM chat_leads WHERE colour='red'").get().n;
console.log('red_count=' + count);

const rows = db
  .prepare(
    `SELECT sessionId, chatId, phone, chatName, colour, bitrixLeadId, bitrixEntityType,
            messageCountSinceClassify, lastClassifiedAt, updatedAt
     FROM chat_leads
     WHERE colour='red'
     ORDER BY updatedAt DESC
     LIMIT 80`,
  )
  .all();

for (const r of rows) {
  console.log(
    JSON.stringify({
      phone: r.phone,
      name: r.chatName,
      chat: String(r.chatId || '').slice(0, 48),
      session: r.sessionId,
      lead: r.bitrixLeadId,
      entity: r.bitrixEntityType,
      classified: r.lastClassifiedAt,
      updated: r.updatedAt,
    }),
  );
}
