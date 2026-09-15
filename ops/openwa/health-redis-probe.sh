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
  echo "=== api redis env ==="; \
  docker compose exec -T openwa-api printenv REDIS_HOST REDIS_PORT QUEUE_ENABLED; \
  echo "=== ping redis hostname from api ==="; \
  docker compose exec -T openwa-api node -e "
    const net=require(\"net\");
    const host=process.env.REDIS_HOST||\"redis\";
    const port=Number(process.env.REDIS_PORT||6379);
    const s=net.connect(port,host,()=>{console.log(\"tcp-ok\",host,port); s.end();});
    s.on(\"error\",e=>{console.log(\"tcp-fail\",host,port,e.message); process.exitCode=1;});
    setTimeout(()=>{console.log(\"tcp-timeout\"); process.exit(1);},3000);
  "; \
  echo "=== ioredis dbsize from api ==="; \
  docker compose exec -T openwa-api node -e "
    const Redis=require(\"ioredis\");
    const r=new Redis({host:process.env.REDIS_HOST||\"redis\",port:Number(process.env.REDIS_PORT||6379),maxRetriesPerRequest:1,connectTimeout:3000});
    r.dbsize().then(n=>{console.log(\"dbsize\",n); return r.keys(\"bull:*\");}).then(k=>{console.log(\"bullKeys\",k.slice(0,30)); console.log(\"bullCount\",k.length); return r.quit();}).catch(e=>{console.error(e); process.exit(1);});
  "; \
  echo "=== redis container dbsize ==="; \
  docker compose --profile redis exec -T redis redis-cli DBSIZE; \
  docker compose --profile redis exec -T redis redis-cli KEYS \"bull:*\" | head; \
  echo "=== recent health logs ==="; \
  docker compose logs openwa-api --tail 200 --no-log-prefix 2>&1 | grep -iE \"health job|ConversationHealth|skip lead|Custom Id|ERROR\" | tail -30; \
  echo "=== processor file ==="; \
  docker compose exec -T openwa-api ls /app/dist/modules/conversation-health/conversation-health.processor.js'
