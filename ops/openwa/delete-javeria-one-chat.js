/**
 * One-off: remove one Linked-phones thread from OpenWA storage.
 *
 * Session javeria-bibi (971507438293) × chat 971502188528 (LID 110991299846152@lid).
 * Refuses to run if those identities do not still match. Does not take arguments.
 */
const fs = require("fs");
const Database = require("better-sqlite3");

const SESSION_ID = "0f06b511-0c72-412c-8504-e1795acc6235";
const SESSION_NAME = "javeria-bibi";
const SESSION_PHONE = "971507438293";
const CHAT_ID = "110991299846152@lid";
const LID = "110991299846152";
const CUSTOMER_PHONE = "971502188528";

function sqliteFile() {
  const candidates = [
    process.env.DATABASE_NAME,
    "/app/data/openwa.sqlite",
    "./data/openwa.sqlite",
    "/data/openwa.sqlite",
  ].filter(Boolean);
  const file = candidates.find((p) => fs.existsSync(p));
  if (!file) {
    throw new Error("no sqlite file found in: " + candidates.join(", "));
  }
  return file;
}

async function dropFromLiveList() {
  const key = process.env.API_MASTER_KEY || process.env.API_KEY;
  if (!key) {
    console.log("live-list=skip (no API key)");
    return;
  }
  const response = await fetch(`http://127.0.0.1:2785/api/sessions/${SESSION_ID}/chats/delete`, {
    method: "POST",
    headers: { "X-API-Key": key, "Content-Type": "application/json" },
    body: JSON.stringify({ chatId: CHAT_ID }),
  });
  const text = await response.text();
  console.log(`live-list-http=${response.status}`);
  if (!response.ok) {
    console.log(`live-list-body=${text.slice(0, 200)}`);
  }
}

function deleteFromDb() {
  const db = new Database(sqliteFile(), { fileMustExist: true });
  try {
    const session = db
      .prepare("SELECT id, name, phone FROM sessions WHERE id = ?")
      .get(SESSION_ID);
    if (!session || session.name !== SESSION_NAME || String(session.phone) !== SESSION_PHONE) {
      throw new Error("session identity mismatch; refusing to delete");
    }
    const mapping = db.prepare("SELECT lid, phone FROM lid_mappings WHERE lid = ?").get(LID);
    if (!mapping || String(mapping.phone) !== CUSTOMER_PHONE) {
      throw new Error("lid/phone mismatch; refusing to delete");
    }

    const before = db
      .prepare("SELECT COUNT(*) AS n FROM messages WHERE sessionId = ? AND chatId = ?")
      .get(SESSION_ID, CHAT_ID).n;
    const other = db
      .prepare("SELECT COUNT(*) AS n FROM messages WHERE chatId = ? AND sessionId != ?")
      .get(CHAT_ID, SESSION_ID).n;

    const rowids = db
      .prepare("SELECT rowid FROM messages WHERE sessionId = ? AND chatId = ?")
      .all(SESSION_ID, CHAT_ID)
      .map((r) => r.rowid);

    const tx = db.transaction(() => {
      const delFts = db.prepare("INSERT INTO messages_fts(messages_fts, rowid) VALUES ('delete', ?)");
      for (const rowid of rowids) {
        delFts.run(rowid);
      }
      const messages = db
        .prepare("DELETE FROM messages WHERE sessionId = ? AND chatId = ?")
        .run(SESSION_ID, CHAT_ID).changes;
      const leads = db
        .prepare("DELETE FROM chat_leads WHERE sessionId = ? AND chatId = ?")
        .run(SESSION_ID, CHAT_ID).changes;
      const profiles = db
        .prepare("DELETE FROM chat_profiles WHERE sessionId = ? AND chatId = ?")
        .run(SESSION_ID, CHAT_ID).changes;
      const mappings = db
        .prepare("DELETE FROM conversation_mappings WHERE sessionId = ? AND chatId = ?")
        .run(SESSION_ID, CHAT_ID).changes;
      const statuses = db
        .prepare("DELETE FROM status_updates WHERE sessionId = ? AND contactJid = ?")
        .run(SESSION_ID, CHAT_ID).changes;
      return { messages, leads, profiles, mappings, statuses };
    });

    const deleted = tx();
    const after = db
      .prepare("SELECT COUNT(*) AS n FROM messages WHERE sessionId = ? AND chatId = ?")
      .get(SESSION_ID, CHAT_ID).n;
    const sessionLeft = db
      .prepare("SELECT COUNT(*) AS n FROM messages WHERE sessionId = ?")
      .get(SESSION_ID).n;

    console.log(`messages-before=${before}`);
    console.log(`messages-deleted=${deleted.messages}`);
    console.log(`messages-after=${after}`);
    console.log(`other-sessions-same-jid=${other}`);
    console.log(`session-messages-left=${sessionLeft}`);
    console.log(`chat-leads-deleted=${deleted.leads}`);
    console.log(`chat-profiles-deleted=${deleted.profiles}`);
    console.log(`conversation-mappings-deleted=${deleted.mappings}`);
    console.log(`status-updates-deleted=${deleted.statuses}`);
    if (after !== 0) {
      throw new Error("target chat still has messages");
    }
  } finally {
    db.close();
  }
}

(async () => {
  await dropFromLiveList();
  deleteFromDb();
  console.log("one-chat-delete=PASS");
})().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
