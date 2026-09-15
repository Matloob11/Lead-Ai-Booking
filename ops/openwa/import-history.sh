#!/usr/bin/env bash
#
# Pull a linked number's history into the database, as far back as WhatsApp will
# still give it.
#
# The importer already exists and runs on its own after a link or a reconnect —
# ten days on a first link, from the last checkpoint on a reconnect. This script
# only moves the checkpoint back and lets that same importer run. It adds no
# speed, no parallelism, and no larger batches: the phone is a real handset on a
# personal account, and the fastest way to lose a number is to make it look like
# something other than a person's phone.
#
#   ops/openwa/import-history.sh 971502938395
#   ops/openwa/import-history.sh 971502938395 --days 30
#   ops/openwa/import-history.sh minahil --dry-run
#
# What WhatsApp will give is not the same as everything that was ever said. A
# linked device only ever sees what WhatsApp still holds for it, so this reports
# what actually arrived rather than claiming a number.

set -euo pipefail

HOST="root@187.127.123.235"
KEY="C:/Users/Matloob/.ssh/hostinger_codex"
APP="/opt/openwa-trial/OpenWA"
VOLUME="/var/lib/docker/volumes/openwa_openwa-data/_data"
DB="$VOLUME/openwa.sqlite"

# Far enough back that the window is "whatever is left", without pretending to a
# date that means anything. The importer asks WhatsApp for everything since this;
# WhatsApp answers with what it still has.
ALL_SINCE="2015-01-01T00:00:00.000Z"

remote() { ssh -i "$KEY" -o BatchMode=yes "$HOST" "$@"; }

# Runs a node snippet against the SQLite file inside a throwaway container. The
# app image is used because it is the only thing on the box carrying a node with
# `node:sqlite`; the volume is mounted read-only unless a write is asked for.
#
# The snippet travels base64-encoded. Sent as a quoted argument it has to survive
# this shell, ssh's own re-parse, and the remote shell — and these snippets are
# full of the quotes and parentheses that each of those layers reads differently.
db() { # db <ro|rw> <script>
  local mode="$1"; shift
  local b64
  b64=$(printf '%s' "$1" | base64 -w0)
  remote "echo $b64 | base64 -d > /tmp/owa-q.js && docker run --rm -v $VOLUME:/x:$mode -v /tmp/owa-q.js:/q.js:ro --entrypoint node openwa-openwa-api /q.js 2>&1 | grep -viE 'experimental|trace-warnings'"
}

usage() {
  cat <<'TXT'
usage: import-history.sh <number|session-name> [--days N] [--dry-run]

  <number|session-name>  which linked phone. Required, and never guessed: this
                         restarts that session, so it is not something to run
                         against whatever happens to be first in the list.
  --days N               only the last N days. Default is as far back as
                         WhatsApp will go.
  --dry-run              say what would happen and change nothing.

The session must be READY. A disconnected phone cannot be asked for history —
connect it first from Linked devices, then run this.
TXT
}

TARGET=""; DAYS=""; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --days) DAYS="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $1" >&2; usage; exit 2 ;;
    *) TARGET="$1"; shift ;;
  esac
done

[ -n "$TARGET" ] || { usage; exit 2; }
if [ -n "$DAYS" ] && ! [[ "$DAYS" =~ ^[0-9]+$ ]]; then
  echo "--days takes a whole number of days" >&2; exit 2
fi

if [ -n "$DAYS" ]; then
  SINCE=$(node -e "process.stdout.write(new Date(Date.now() - $DAYS*86400000).toISOString())")
  WINDOW="the last $DAYS days"
else
  SINCE="$ALL_SINCE"
  WINDOW="as far back as WhatsApp will go"
fi

echo "== target: $TARGET"
echo "== window: $WINDOW"

# Identify the session and refuse anything that is not ready, before touching it.
INFO=$(db ro "
const s=require('node:sqlite');
const db=new s.DatabaseSync('/x/openwa.sqlite',{readOnly:true});
const row=db.prepare('SELECT id,name,phone,status FROM sessions WHERE phone=? OR name=?').get('$TARGET','$TARGET');
if(!row){console.log('NOTFOUND');process.exit(0)}
const n=db.prepare('SELECT count(*) c FROM messages WHERE sessionId=?').get(row.id).c;
console.log([row.id,row.name,row.phone,row.status,n].join('|'));
")

case "$INFO" in
  *NOTFOUND*) echo "No linked phone matches '$TARGET'. Run it against a number or a session name." >&2; exit 1 ;;
esac

IFS='|' read -r SID SNAME SPHONE SSTATUS BEFORE <<<"$(echo "$INFO" | tail -1)"
echo "== session: $SNAME ($SPHONE) — $SSTATUS"
echo "== messages already stored: $BEFORE"

if [ "$SSTATUS" != "ready" ]; then
  echo
  echo "Refusing: this session is '$SSTATUS'. WhatsApp only hands history to a" >&2
  echo "connected device — connect it from Linked devices first." >&2
  exit 1
fi

if [ "$DRY" = "1" ]; then
  echo
  echo "Dry run. Would rewind this session's checkpoint to $SINCE and restart it."
  exit 0
fi

echo "== stopping the app so nothing writes while the checkpoint moves"
remote "cd $APP && docker compose stop openwa-api >/dev/null 2>&1"
sleep 4

echo "== rewinding the checkpoint (nothing is deleted; the unique index refuses duplicates)"
db rw "
const s=require('node:sqlite');
const db=new s.DatabaseSync('/x/openwa.sqlite');
db.prepare('UPDATE sessions SET historyImportedAt=?, syncProgress=0 WHERE id=?').run('$SINCE','$SID');
const r=db.prepare('SELECT historyImportedAt h, syncProgress p FROM sessions WHERE id=?').get('$SID');
console.log('   checkpoint now', r.h, '| progress', r.p);
"

echo "== starting"
remote "cd $APP && docker compose start openwa-api >/dev/null 2>&1"

echo "== importing. This is the ordinary importer at its ordinary pace; it takes"
echo "   as long as it takes rather than leaning on the handset."
LAST=""
for _ in $(seq 1 90); do
  sleep 20
  P=$(db ro "
const s=require('node:sqlite');
const db=new s.DatabaseSync('/x/openwa.sqlite',{readOnly:true});
const r=db.prepare('SELECT syncProgress p FROM sessions WHERE id=?').get('$SID');
const n=db.prepare('SELECT count(*) c FROM messages WHERE sessionId=?').get('$SID').c;
console.log(r.p+' '+n);
" | tail -1)
  [ "$P" = "$LAST" ] || echo "   ${P%% *}% · ${P##* } messages"
  LAST="$P"
  [ "${P%% *}" = "100" ] && break
done

AFTER="${LAST##* }"
echo
echo "== done"
echo "   before : $BEFORE"
echo "   after  : $AFTER"
echo "   added  : $(( AFTER - BEFORE ))"
echo
echo "   Groups and WhatsApp's own system notices are skipped by design, so this"
echo "   counts conversations with people. What did not arrive is history"
echo "   WhatsApp no longer offers this device — not a failure of the import."
