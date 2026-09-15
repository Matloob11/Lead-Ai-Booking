const key = process.env.API_MASTER_KEY || process.env.API_KEY;
if (!key) {
  console.error('master API key is unavailable');
  process.exit(1);
}

async function main() {
  if (process.env.RESOLVE_LID_TO_PHONE !== 'true') {
    throw new Error(`RESOLVE_LID_TO_PHONE=${process.env.RESOLVE_LID_TO_PHONE || ''}`);
  }
  console.log('resolve-lid-runtime=true');

  const response = await fetch('http://127.0.0.1:2785/api/sessions/chats/all', {
    headers: { 'X-API-Key': key },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const chats = Array.isArray(body) ? body : body.chats || body.data || [];
  const lidRows = chats.filter(c => String(c.id || '').endsWith('@lid'));
  const named = lidRows.filter(c => c.name && c.name !== String(c.id).split('@')[0]);
  const phoneLike = named.filter(c => /^\+?\d[\d\s-]{7,}$/.test(String(c.name)));
  console.log(`all-chats-count=${chats.length}`);
  console.log(`lid-rows=${lidRows.length}`);
  console.log(`lid-non-placeholder-names=${named.length}`);
  console.log(`lid-phone-like-names=${phoneLike.length}`);
  console.log(
    `lid-sample=${JSON.stringify(
      lidRows.slice(0, 3).map(c => ({ id: c.id, name: c.name, sessionName: c.sessionName })),
    )}`,
  );
  console.log('all-chats-api=PASS');
}

main().catch(error => {
  console.error(error.message || String(error));
  process.exit(1);
});
