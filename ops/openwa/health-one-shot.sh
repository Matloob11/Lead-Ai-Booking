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
  "$HOST" 'cd /opt/openwa-trial/OpenWA && docker compose exec -T openwa-api node <<'"'"'NODE'"'"'
const Database = require("better-sqlite3");
const db = new Database("/app/data/openwa.sqlite", { readonly: true });
const row = db.prepare("select sessionId, chatId, chatName from messages where chatId like \"%@c.us\" limit 1").get();
console.log("sample", row);
const lid = "77494833127615";
const map = db.prepare("select lid, phone from lid_mappings where lid=?").get(lid);
console.log("knownMap", map);
const chat = db.prepare("select sessionId, chatId, max(chatName) chatName from messages where chatId=?").get(lid + "@lid");
console.log("mappedChat", chat);
const schema = db.prepare("pragma table_info(chat_leads)").all();
console.log("schema", schema);
NODE
echo "=== recent skip vs bitrix ==="
docker compose logs openwa-api --tail 300 --no-log-prefix 2>&1 | grep -E "skip lead|Bitrix|findOrCreate|chat_leads|QueryFailed|SQLITE" | tail -40
'
