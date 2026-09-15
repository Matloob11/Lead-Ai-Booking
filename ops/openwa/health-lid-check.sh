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
ssh.exe -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10 \
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN" \
  "$HOST" 'cd /opt/openwa-trial/OpenWA && docker compose exec -T openwa-api node -e "
const Database=require(\"better-sqlite3\");
const db=new Database(\"/app/data/openwa.sqlite\",{readonly:true});
console.log(\"lid_mappings\", db.prepare(\"select count(*) c from lid_mappings\").get());
console.log(\"sampleMaps\", db.prepare(\"select lid, phone from lid_mappings where phone is not null limit 8\").all());
const chats=db.prepare(\"select distinct chatId from messages where chatId like \\\"%@lid\\\" limit 20\").all().map(r=>r.chatId);
let hit=0, miss=0;
for (const chatId of chats) {
  const lid=chatId.split(\"@\")[0];
  const row=db.prepare(\"select phone from lid_mappings where lid=?\").get(lid);
  if (row&&row.phone) hit++; else miss++;
}
console.log({sampleChats:chats.length, hit, miss});
const cUs=db.prepare(\"select count(distinct chatId) c from messages where chatId like \\\"%@c.us\\\"\").get();
console.log(\"cUsChats\", cUs);
console.log(\"bitrix\", process.env.BITRIX_WEBHOOK_BASE ? \"set\" : \"missing\");
console.log(\"chat_leads\", db.prepare(\"select count(*) c from chat_leads\").get());
"'
