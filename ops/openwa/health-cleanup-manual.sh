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
const db=new Database(\"./data/openwa.sqlite\");
const n=db.prepare(\"delete from chat_leads where id like '\''manual-%'\'' or bitrixLeadId='\''999999'\''\").run();
console.log(\"deleted\", n.changes, \"left\", db.prepare(\"select count(*) c from chat_leads\").get());
"'
