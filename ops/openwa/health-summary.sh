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
  code=$(curl -sS -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:2785/api/health/ready); \
  echo readiness=$code; \
  KEY=$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d "\r"); \
  echo -n env=; docker compose exec -T openwa-api sh -c "printf \"%s \" \"\$QUEUE_ENABLED\" \"\$REDIS_ENABLED\" \"\$REDIS_HOST\" \"\$CONVERSATION_HEALTH_ENABLED\""; echo; \
  echo -n summary=; curl -sS -m 30 -H "X-API-Key: $KEY" http://127.0.0.1:2785/api/conversation-health/summary; echo; \
  echo -n backfill=; curl -sS -m 120 -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" http://127.0.0.1:2785/api/conversation-health/backfill; echo'
