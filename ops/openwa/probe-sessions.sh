#!/usr/bin/env bash
# Probe GET /api/sessions from inside the container. Prints status + count only.
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
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -c '
  code=\$(curl -sS -o /tmp/sess.json -w \"%{http_code}\" -H \"X-API-Key: \$API_MASTER_KEY\" http://127.0.0.1:2785/api/sessions)
  echo sessions_http=\$code
  node -e \"const fs=require(\\\"fs\\\"); let d; try { d=JSON.parse(fs.readFileSync(\\\"/tmp/sess.json\\\",\\\"utf8\\\")); } catch(e) { console.log(\\\"parse=fail\\\"); process.exit(0);} if (!Array.isArray(d)) { console.log(\\\"shape=\\\"+typeof d+(d&&d.statusCode?\\\" statusCode=\\\"+d.statusCode:\\\"\\\")); process.exit(0);} const c={}; for (const s of d) c[s.status]=(c[s.status]||0)+1; console.log(\\\"count=\\\"+d.length); console.log(Object.entries(c).map(([k,v])=>k+\\\"=\\\"+v).join(\\\" \\\"));\"
'"
