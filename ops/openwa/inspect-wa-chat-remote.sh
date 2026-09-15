#!/usr/bin/env bash
# Run WA_CHAT field inspect on the VPS (Bitrix webhook often times out from laptop).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")
BASE="${BITRIX_WEBHOOK_BASE%/}"

"${SSH[@]}" "$HOST" "BITRIX_BASE=$(printf %q "$BASE") python3 -" <<'PY'
import json, os, urllib.request
base = os.environ["BITRIX_BASE"].rstrip("/")

def post(method, payload):
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)

fields = post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": "UF_CRM_WA_CHAT"}}).get("result") or []
print("=== UF_CRM_WA_CHAT meta ===")
print(json.dumps(fields[:1], ensure_ascii=False, indent=2)[:3500])

for lead_id in ["71945", "71909", "71967"]:
    lead = (post("crm.lead.get", {"ID": lead_id}).get("result") or {})
    wa = lead.get("UF_CRM_WA_CHAT") or ""
    mon = lead.get("UF_CRM_AI_MONITOR") or ""
    print(f"\n=== lead {lead_id} ===")
    print("title", lead.get("TITLE"))
    print("wa_len", len(str(wa)))
    print("wa_repr_head", repr(str(wa)[:500]))
    text = str(wa).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    print("line_count", len(lines), "has_real_nl", "\n" in str(wa))
    for i, line in enumerate(lines[:15]):
        print(f"L{i}", repr(line[:140]))
    print("monitor_repr", repr(str(mon)[:300]))
PY
