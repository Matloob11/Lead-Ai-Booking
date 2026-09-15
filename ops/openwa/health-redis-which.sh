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
  "$HOST" 'set -e; cd /opt/openwa-trial/OpenWA; \
  echo "=== docker redis containers ==="; \
  docker ps -a --format "{{.Names}} {{.Image}} {{.Ports}} {{.Networks}}" | grep -i redis || true; \
  echo "=== api resolve redis ==="; \
  docker compose exec -T openwa-api getent hosts redis || docker compose exec -T openwa-api nslookup redis || true; \
  echo "=== openwa-redis IP ==="; \
  docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{.NetworkID}}{{end}}" openwa-redis 2>/dev/null || true; \
  echo "=== api networks ==="; \
  docker inspect -f "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}}={{\$v.IPAddress}} {{end}}" openwa-api; \
  echo "=== redis INFO from api ==="; \
  docker compose exec -T openwa-api node -e "
    const Redis=require(\"ioredis\");
    const r=new Redis({host:process.env.REDIS_HOST||\"redis\",port:6379,maxRetriesPerRequest:1});
    r.info(\"server\").then(i=>{console.log(i.split(\"\\n\").filter(l=>/redis_version|run_id|tcp_port|process_id/.test(l)).join(\"\\n\")); return r.quit();});
  "; \
  echo "=== redis INFO from openwa-redis ==="; \
  docker compose --profile redis exec -T redis redis-cli INFO server | grep -E \"redis_version|run_id|tcp_port|process_id\"; \
  echo "=== a7 redis? ==="; \
  docker ps --format "{{.Names}}" | grep -i redis'
