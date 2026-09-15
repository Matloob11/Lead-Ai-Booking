#!/usr/bin/env bash
# Stop surplus qr_ready Chromium engines that are looping QR generation and
# starving Start/list. Does not stop shehreen (operator is scanning) and does
# not stop any ready session. Does not logout (credentials stay on disk).
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
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -s" <<'REMOTE'
set -eu
KEEP_SHEHREEN=a7025bf0-5adb-49e6-bea1-a70252cfb592
echo pids_before=$(ps aux | wc -l)
# IDs of idle qr_ready engines (not shehreen). Names only in comments for the operator log.
# abdul-qadir heram hina-recepstions marketting neha qasim shaid-mamo
for id in \
  6823c3b3-ab86-4ad3-b028-da7fa430e0d3 \
  14e1f3d5-cbb4-40b9-9b4e-79370aa78499 \
  5820f7fb-30f5-4430-9871-21a9aec107c1 \
  9e48197b-8f04-4f2d-bbed-c3af709fb2b9 \
  b5b3b068-0f67-4860-a9cd-f76723c21d00 \
  cce2f35b-ef92-4898-a8c2-a2cf2509981d \
  6d8abdda-86f0-402f-88bd-4c95cc5fb650
do
  if [ "$id" = "$KEEP_SHEHREEN" ]; then
    echo skip_shehreen
    continue
  fi
  code=$(curl -sS -o /tmp/stop.body -w "%{http_code}" --max-time 90 \
    -X POST -H "X-API-Key: $API_MASTER_KEY" \
    "http://127.0.0.1:2785/api/sessions/$id/stop" || echo curl_fail)
  echo "stop $id $code"
done
echo pids_after=$(ps aux | wc -l)
code=$(curl -sS -o /tmp/sess.json -w "%{http_code}" -H "X-API-Key: $API_MASTER_KEY" http://127.0.0.1:2785/api/sessions)
echo sessions_http=$code
node -e '
const d=JSON.parse(require("fs").readFileSync("/tmp/sess.json","utf8"));
if (!Array.isArray(d)) { console.log("shape=not-array"); process.exit(0); }
const c={};
for (const s of d) {
  c[s.status]=(c[s.status]||0)+1;
  if (s.status==="ready") console.log("ready "+s.name);
  if (s.status==="qr_ready") console.log("qr_ready "+s.name);
}
console.log("count="+d.length);
console.log(Object.entries(c).map(([k,v])=>k+"="+v).join(" "));
'
REMOTE
