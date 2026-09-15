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
  KEY=$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d "\r"); \
  echo -n summary=; curl -sS -m 30 -H "X-API-Key: $KEY" http://127.0.0.1:2785/api/conversation-health/summary; echo; \
  echo -n leads=; docker compose exec -T openwa-api node -e "
    const Database=require(\"better-sqlite3\");
    const db=new Database(\"/app/data/openwa.sqlite\",{readonly:true});
    const n=db.prepare(\"select count(*) as c from chat_leads\").get();
    const coloured=db.prepare(\"select count(*) as c from chat_leads where colour is not null\").get();
    console.log(JSON.stringify({total:n.c,coloured:coloured.c}));
  "; echo; \
  docker compose logs openwa-api --tail 30 --no-log-prefix 2>&1 | grep -E "ConversationHealth|Bitrix|ERROR|backfill|classify" | tail -20 || true'
