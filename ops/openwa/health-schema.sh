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
  "$HOST" "cd /opt/openwa-trial/OpenWA && docker compose exec -T openwa-api node -e '
const Database=require(\"better-sqlite3\");
const db=new Database(\"./data/openwa.sqlite\");
console.log(db.prepare(\"pragma table_info(chat_leads)\").all());
try {
  db.prepare(\"insert into chat_leads (id, sessionId, chatId, phone, bitrixLeadId, messageCountSinceClassify, createdAt, updatedAt) values (?,?,?,?,?,?,datetime(\\\"now\\\"),datetime(\\\"now\\\"))\").run(\"test-id\",\"sess\",\"971502254700@c.us\",\"971502254700\",\"1\",0);
  console.log(\"insert-ok\", db.prepare(\"select count(*) c from chat_leads\").get());
  db.prepare(\"delete from chat_leads where id=?\").run(\"test-id\");
} catch(e) { console.error(\"insert-fail\", e.message); }
'"
