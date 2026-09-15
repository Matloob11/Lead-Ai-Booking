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
  docker compose exec -T openwa-api sh -c "ls /app/dist/modules/conversation-health/ | grep -E processor|enqueue"; \
  echo "=== all bull keys ==="; \
  docker compose --profile redis exec -T redis redis-cli KEYS "bull:*" | head -50; \
  echo "=== redis dbsize ==="; \
  docker compose --profile redis exec -T redis redis-cli DBSIZE; \
  echo "=== sample chatIds ==="; \
  docker compose exec -T openwa-api node -e "
    const Database=require(\"better-sqlite3\");
    const db=new Database(\"/app/data/openwa.sqlite\",{readonly:true});
    const rows=db.prepare(\"select chatId, count(*) c from messages group by chatId order by c desc limit 15\").all();
    console.log(rows);
  "'
