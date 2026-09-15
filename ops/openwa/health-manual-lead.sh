#!/usr/bin/env bash
set -euo pipefail
HOST="root@187.127.123.235"
KEY="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
ssh.exe -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 \
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN" \
  "$HOST" 'cd /opt/openwa-trial/OpenWA && docker compose exec -T openwa-api node -e "
(async () => {
  const base = (process.env.BITRIX_WEBHOOK_BASE||\"\").replace(/\\/+\$/,\"\");
  console.log(\"bitrixBaseChars\", base.length);
  const phone = \"971502254700\";
  const findRes = await fetch(base + \"/crm.duplicate.findbycomm.json\", {
    method: \"POST\",
    headers: {\"Content-Type\":\"application/json\"},
    body: JSON.stringify({entity_type:\"LEAD\", type:\"PHONE\", values:[phone, \"+\"+phone]}),
  });
  const findJson = await findRes.json();
  console.log(\"find\", JSON.stringify(findJson).slice(0,300));
  const Database=require(\"better-sqlite3\");
  const db=new Database(\"./data/openwa.sqlite\");
  const id=\"manual-\"+Date.now();
  db.prepare(\"INSERT INTO chat_leads (id, sessionId, chatId, phone, chatName, bitrixLeadId, colour, messageCountSinceClassify, createdAt, updatedAt) VALUES (?,?,?,?,?,?,?,?,datetime('\''now'\''),datetime('\''now'\''))\").run(
    id,
    \"5820f7fb-30f5-4430-9871-21a9aec107c1\",
    \"971502254700@c.us\",
    phone,
    null,
    \"999999\",
    null,
    0
  );
  console.log(\"leadsAfter\", db.prepare(\"select count(*) c from chat_leads\").get());
  console.log(\"row\", db.prepare(\"select * from chat_leads where id=?\").get(id));
})().catch(e => { console.error(e); process.exit(1); });
"'
