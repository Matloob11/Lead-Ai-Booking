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
  "$HOST" 'cd /opt/openwa-trial/OpenWA && \
  docker compose exec -T openwa-api sh -c "grep -c resolvePhone /app/dist/modules/conversation-health/conversation-health.service.js; grep -c lidRepo /app/dist/modules/conversation-health/conversation-health.service.js; grep -c \"skip lead\" /app/dist/modules/conversation-health/conversation-health.service.js"; \
  docker compose exec -T openwa-api node -e "
const Database=require(\"better-sqlite3\");
const db=new Database(process.env.DATABASE_NAME||\"/app/data/openwa.sqlite\",{readonly:true});
console.log(\"db\", process.env.DATABASE_NAME||\"/app/data/openwa.sqlite\");
console.log(\"leads\", db.prepare(\"select count(*) c from chat_leads\").get());
console.log(\"cUs\", db.prepare(\"select sessionId, chatId from messages where chatId like '\''%@c.us'\'' group by sessionId, chatId limit 3\").all());
const lid=\"77494833127615\";
console.log(\"map\", db.prepare(\"select * from lid_mappings where lid=?\").get(lid));
console.log(\"chat\", db.prepare(\"select sessionId, chatId, chatName from messages where chatId=? limit 1\").get(lid+\"@lid\"));
"; \
  echo BITRIX=$(docker compose exec -T openwa-api printenv BITRIX_WEBHOOK_BASE | wc -c); \
  docker compose logs openwa-api --tail 500 --no-log-prefix 2>&1 | grep -c \"skip lead\" || true; \
  docker compose logs openwa-api --tail 500 --no-log-prefix 2>&1 | grep -c \"health job backfill\" || true'
