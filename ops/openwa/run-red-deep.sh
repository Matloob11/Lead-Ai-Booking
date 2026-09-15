#!/usr/bin/env bash
# Pull AI Monitor timeline reasons + message snippets for RED chats.
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

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
BASE=$(grep -E '^BITRIX_WEBHOOK_BASE=' .env | head -1 | cut -d= -f2- | tr -d '\r"')
export BASE

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

docker compose exec -T openwa-api node >"$TMP" <<'NODE'
const Database=require('better-sqlite3');
const db=new Database(process.env.DATABASE_NAME||'/app/data/openwa.sqlite',{readonly:true});
const reds=db.prepare("SELECT sessionId, chatId, phone, chatName, bitrixLeadId, bitrixEntityType FROM chat_leads WHERE colour='red' ORDER BY updatedAt DESC").all();
console.log(JSON.stringify({reds}));
for (const r of reds) {
  const msgs=db.prepare(`
    SELECT direction, body, type, timestamp
    FROM messages
    WHERE sessionId=? AND chatId=? AND type NOT IN ('system','revoked')
    ORDER BY timestamp DESC
    LIMIT 40
  `).all(r.sessionId, r.chatId);
  // reverse to chronological for reading
  msgs.reverse();
  const lines=msgs.map(m=>{
    const who=m.direction==='outgoing'?'AGENT':'CLIENT';
    const body=(m.body||'').replace(/\s+/g,' ').trim().slice(0,180) || `[${m.type}]`;
    return `${who}: ${body}`;
  });
  console.log('---CHAT---');
  console.log(JSON.stringify({phone:r.phone, lead:r.bitrixLeadId, entity:r.bitrixEntityType, name:r.chatName, n:lines.length, lines}));
}
NODE

python3 - "$TMP" <<'PY'
import json, os, re, urllib.parse, urllib.request, sys
from collections import Counter

base = os.environ["BASE"].rstrip("/")
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
meta = json.loads(raw[0])
reds = meta["reds"]
print(f"red_count={len(reds)}")

def bx(method, params):
    url = f"{base}/{method}.json"
    data = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)

reasons = []
print("\n=== AI timeline reasons ===")
for r in reds:
    lid = r["bitrixLeadId"]
    entity = (r.get("bitrixEntityType") or "lead").upper()
    reason = "(no AI comment)"
    try:
        # Lead timeline
        if "DYNAMIC" in entity:
            # Owner Data comments
            res = bx("crm.timeline.comment.list", {
                "filter[ENTITY_ID]": lid,
                "filter[ENTITY_TYPE]": "dynamic_1042",
            })
        else:
            res = bx("crm.timeline.comment.list", {
                "filter[ENTITY_ID]": lid,
                "filter[ENTITY_TYPE]": "lead",
            })
        comments = res.get("result") or []
        if isinstance(comments, dict):
            comments = list(comments.values()) if comments else []
        # newest first-ish
        for c in comments:
            text = c.get("COMMENT") or c.get("comment") or ""
            if "AI Monitor" in text or "Reason:" in text or "🔴" in text:
                m = re.search(r"Reason:\s*(.+)", text)
                reason = m.group(1).strip() if m else text.replace("\n", " | ")[:220]
                break
        # fallback: activity list
        if reason == "(no AI comment)":
            res2 = bx("crm.timeline.list", {"filter[ENTITY_ID]": lid, "filter[ENTITY_TYPE]": "lead"})
            items = res2.get("result") or []
            if isinstance(items, dict):
                items = list(items.values())
            for it in items:
                text = json.dumps(it, ensure_ascii=False)
                if "Reason:" in text or "AI Monitor" in text:
                    m = re.search(r"Reason:\\?\s*([^\\\"\n]+)", text)
                    reason = m.group(1).strip() if m else text[:220]
                    break
    except Exception as e:
        reason = f"ERR {e}"
    print(f"{r.get('phone')}|{lid}|{reason}")
    reasons.append(reason)

print("\n=== reason frequency ===")
for k,v in Counter(reasons).most_common():
    print(f"{v}x | {k}")

# Parse chat blocks for keyword signals
print("\n=== chat keyword signals (from last ~40 msgs) ===")
blocks = []
cur = None
for line in raw[1:]:
    if line == "---CHAT---":
        cur = None
        continue
    if line.startswith("{"):
        try:
            cur = json.loads(line)
            blocks.append(cur)
        except Exception:
            pass

kw = [
    ("personal/private number", re.compile(r"\b(personal|private)\b.*\b(number|num|phone)\b|\bmera (number|num)\b|\bmy personal\b", re.I)),
    ("outside / without company", re.compile(r"\b(outside|bina company|without company|direct deal|side deal|off.?book)\b", re.I)),
    ("commission / cut", re.compile(r"\b(commission|commision|cut|share)\b", re.I)),
    ("cash deal", re.compile(r"\bcash\b", re.I)),
    ("don't tell / secret", re.compile(r"\b(don'?t tell|dont tell|secret|chup|mat batana|between us)\b", re.I)),
    ("transfer / other agency", re.compile(r"\b(other agency|transfer lead|apni company|my company)\b", re.I)),
]
sig = Counter()
examples = {k: [] for k,_, in [(a,b) for a,b in kw]}
# fix
examples = {name: [] for name, _ in kw}

for b in blocks:
    text = "\n".join(b.get("lines") or [])
    hit = False
    for name, rx in kw:
        if rx.search(text):
            sig[name] += 1
            if len(examples[name]) < 2:
                # grab matching line
                for ln in b.get("lines") or []:
                    if rx.search(ln):
                        examples[name].append(f"{b.get('phone')}: {ln[:140]}")
                        break
            hit = True
    if not hit:
        sig["no clear red keyword in recent msgs"] += 1

for name, n in sig.most_common():
    print(f"{n}x | {name}")
    for ex in examples.get(name, [])[:2]:
        print(f"    e.g. {ex}")
PY
REMOTE
