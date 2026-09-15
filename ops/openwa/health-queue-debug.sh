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
  echo "=== redis keys ==="; \
  docker compose --profile redis exec -T redis redis-cli KEYS "*conversation*" | head -40; \
  echo "=== waiting/active/failed/completed ==="; \
  Q=bull:conversation-health-queue; \
  for s in wait active delayed failed completed; do \
    echo -n "$s="; docker compose --profile redis exec -T redis redis-cli LLEN "${Q}:${s}" 2>/dev/null || \
      docker compose --profile redis exec -T redis redis-cli ZCARD "${Q}:${s}" 2>/dev/null || echo "?"; \
  done; \
  echo "=== tables ==="; \
  docker compose exec -T openwa-api node -e "
    const Database=require(\"better-sqlite3\");
    const db=new Database(\"/app/data/openwa.sqlite\",{readonly:true});
    const tables=db.prepare(\"select name from sqlite_master where type='\''table'\'' and name like '\''%lead%'\''\").all();
    console.log(tables);
    try { console.log(\"chat_leads\", db.prepare(\"select count(*) c from chat_leads\").get()); } catch(e){ console.log(String(e)); }
  "; \
  echo "=== processor in image? ==="; \
  docker compose exec -T openwa-api sh -c "ls -la dist/modules/conversation-health/ 2>/dev/null | head -20 || ls -la /app/dist/modules/conversation-health/ 2>/dev/null | head -20"; \
  echo "=== boot grep ==="; \
  docker compose logs openwa-api --tail 400 --no-log-prefix 2>&1 | grep -iE "conversation|ConversationHealth|bull|Worker|failed" | tail -40'
