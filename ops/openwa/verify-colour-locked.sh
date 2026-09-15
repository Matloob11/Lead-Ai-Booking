#!/usr/bin/env bash
set -euo pipefail
HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=25 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api node -e \"const Database=require('better-sqlite3'); const db=new Database(process.env.DATABASE_NAME||'/app/data/openwa.sqlite',{readonly:true}); const cols=db.prepare('PRAGMA table_info(chat_leads)').all().map(c=>c.name); console.log(cols.join(',')); console.log('colourLocked='+cols.includes('colourLocked'));\" && docker compose exec -T openwa-api printenv CONVERSATION_HEALTH_OVERRIDE_PASSWORD"
