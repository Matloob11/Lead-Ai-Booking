const key = process.env.API_MASTER_KEY || process.env.API_KEY;
if (!key) {
  console.error('master API key is unavailable');
  process.exit(1);
}

async function main() {
  const response = await fetch('http://127.0.0.1:2785/api/sessions/chats/all', {
    headers: { 'X-API-Key': key },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${JSON.stringify(body).slice(0, 200)}`);
  }

  const chats = Array.isArray(body) ? body : body.chats || body.data || [];
  const sample = chats.slice(0, 3).map(chat => ({
    id: chat.id || chat.chatId,
    sessionName: chat.sessionName,
    sessionId: chat.sessionId,
    removed: chat.removed,
    canOpenThread: chat.canOpenThread,
    name: chat.name || chat.contactName,
  }));

  console.log(`all-chats-http=${response.status}`);
  console.log(`all-chats-count=${chats.length}`);
  console.log(`all-chats-sample=${JSON.stringify(sample)}`);

  const hasFields =
    chats.length === 0 || ('sessionName' in chats[0] && 'canOpenThread' in chats[0] && 'removed' in chats[0]);
  if (!hasFields) {
    throw new Error('all-chats-shape=FAIL missing sessionName/canOpenThread/removed');
  }
  console.log('all-chats-shape=PASS');
}

main().catch(error => {
  console.error(error.message || String(error));
  process.exit(1);
});
