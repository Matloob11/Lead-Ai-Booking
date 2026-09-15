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
const Redis=require(\"ioredis\");
const r=new Redis({host:process.env.REDIS_HOST||\"redis\",port:6379,maxRetriesPerRequest:1});
const q=\"bull:conversation-health-queue\";
(async()=>{
  for (const k of [\"wait\",\"active\",\"paused\",\"delayed\",\"failed\",\"completed\",\"prioritized\"]) {
    const t = await r.type(q+\":\"+k);
    let n=0;
    if (t===\"list\") n=await r.llen(q+\":\"+k);
    else if (t===\"zset\") n=await r.zcard(q+\":\"+k);
    else if (t===\"set\") n=await r.scard(q+\":\"+k);
    else if (t===\"none\") n=0;
    else n=t;
    console.log(k, n, t);
  }
  const failed=await r.zrange(q+\":failed\",0,2);
  console.log(\"failedSample\", failed);
  if (failed[0]) console.log(\"failedJob\", await r.hgetall(q+\":\"+failed[0]));
  const wait=await r.lrange(q+\":wait\",0,2);
  console.log(\"waitSample\", wait);
  await r.quit();
})().catch(e=>{console.error(e); process.exit(1);});
"'
