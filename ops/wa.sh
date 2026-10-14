#!/usr/bin/env bash
#
# The small, fixed vocabulary this project uses to talk to the live server.
#
# It exists so the permission allowlist can hold something narrow. Allowing
# `ssh` itself would allow every command there is — `ssh host <anything>` is
# arbitrary remote execution — and that matters more here than in most repos:
# this codebase reads customer messages, webhook bodies, template text and
# uploaded filenames into an AI agent's context, all of it written by people
# outside the company. A sentence in a customer's message must not be able to
# reach production.
#
# So the agent is allowed to run *this*, and this decides what may run there.
# Every path is checked against /opt/a7-wa, every service name against the real
# list, and every query runs inside a transaction the database itself refuses
# to let write. Adding a subcommand here is a deliberate act; widening `ssh`
# would have been an accident waiting to be made.
#
# Usage:
#   ops/wa.sh ps                          both stacks, container states
#   ops/wa.sh logs qr app [200]           container logs
#   ops/wa.sh sql qr "SELECT 1"           read-only query (writes are refused)
#   ops/wa.sh sum /opt/a7-wa/panel/x.js   checksum of a deployed file
#   ops/wa.sh get /app/assets/x.js        fetch from the public site
#   ops/wa.sh push local remote           copy one file to the server
#   ops/wa.sh sync src /opt/a7-wa/wa-qr   copy a directory to the server
#   ops/wa.sh build openwa                rebuild the OpenWA trial stack
#   ops/wa.sh panel [stale…]              publish bitrix/public to /opt/a7-wa/panel
#   ops/wa.sh agent-reports-deploy        publish agent-reports stack + nginx location
#   ops/wa.sh agent-reports-check         compose + public /agent-reports/ health
#   ops/wa.sh agent-reports-fix-nginx    move/refresh /agent-reports/ into :443 server
#   ops/wa.sh agent-reports-sync-owner-phones [--dry-run] [--limit N] [--all]
#   ops/wa.sh build qr app                rebuild an image
#   ops/wa.sh restart qr app              restart services
#   ops/wa.sh up app [service]            recreate the app stack, or one service (after a build)
#   ops/wa.sh openwa-state                image, compose, health, and disk state
#   ops/wa.sh openwa-cold-backup          stop API and archive fixed data volume
#   ops/wa.sh openwa-inspect-asma-backup  inspect fixed pre-delete backup read-only
#   ops/wa.sh openwa-restore-asma         cold-backup then guarded Asma-only restore
#   ops/wa.sh openwa-verify-asma-restore  prove stored chats + agent-10 scope
#   ops/wa.sh openwa-browser-verify-asma  open restored chat in live headless dashboard
#   ops/wa.sh openwa-stop-restored-asma    stop restored Asma engine; keep row/history
#   ops/wa.sh openwa-arm-restored-asma     prevent boot auto-start before profile-reset deploy
#   ops/wa.sh openwa-reset-restored-asma   invoke guarded profile reset after deploy
#   ops/wa.sh openwa-delete-javeria-one-chat  one-off: drop one javeria-bibi thread
#   ops/wa.sh openwa-force-recreate       force-recreate OpenWA API after build
#   ops/wa.sh unlock                      clear stale Chromium profile locks
#   ops/wa.sh migrate                     apply pending Django migrations (app stack)
#   ops/wa.sh migrate-new-image           the same, from the image just built, before `up`
#   ops/wa.sh leadai-tests                Lead AI tests in the new image, throwaway test DB, nothing leaves
#   ops/wa.sh probe-leadai-turn           3 real assistant turns on live data + key, rolled back, nothing sent
#   ops/wa.sh leadai-eval [--only ID] [--repeat N] [--show] [--list]  the prompt vs the real model, scripted chats
#   ops/wa.sh leadai-eval-draft [same]      the same on the pushed build context (beat), before a build
#   ops/wa.sh django-check                the two checks CLAUDE.md requires
#   ops/wa.sh deploy-villa-nova2            one-off: villa_nova2 to missing WABAs
#   ops/wa.sh sync-all-templates            pull Alots templates for every Official WABA
#   ops/wa.sh keep-sheet-official-numbers   hide Official numbers not on the Dubai sheet
#   ops/wa.sh assign-18-971-44              one 44 + one 971 for the named 18 agents
#   ops/wa.sh probe-openai-key              key set? 8-hex fingerprint, model, one-token call result
#   ops/wa.sh set-leadai-openai-key FILE    Lead AI's own key (LEADAI_OPENAI_API_KEY) from a local file; main key untouched
#   ops/wa.sh probe-leadai-key              Lead AI key as a new container reads it: fingerprint + one 1-token call
#   ops/wa.sh probe-leadai-notify           one test Bitrix notification to user 2311 + the tool's refusals
#   ops/wa.sh probe-send-404                why Official send HTTP 404 on 772479489292535 (read-only)
#   ops/wa.sh probe-nabiha-500              NABIHA-44 / Matloob test send 500 (read-only)
#   ops/wa.sh test [apps/x/tests/test_y.py] pytest inside the live web image (needs pytest there)
#   ops/wa.sh probe-template-header-media  forced-login checks of the header-media route
#   ops/wa.sh probe-crm-entities           live image understands deal/contact campaign rows (no send)
#   ops/wa.sh probe-media-template-path    can the stack mint a media-template sample handle? yes/no + session state
#   ops/wa.sh probe-gateway-upload         gateway brokers Meta resumable upload with our API key? (1 tiny PNG, no template)
#   ops/wa.sh set-meta-graph-token FILE    write META_GRAPH_ACCESS_TOKEN from FILE's first line, recreate web/worker/beat
#   ops/wa.sh set-alots-ui-cookie FILE     store the alots panel session (Cookie header in FILE), recreate web/worker/beat
#   ops/wa.sh raise-upload-limit            Official + OpenWA nginx body size → 1024m
#   ops/wa.sh ensure-crm-lead-secret HEX    set CRM_LEAD_WA_SECRET if empty (64 hex)
#   ops/wa.sh submit-leadbot-template       submit a7_lead_enquiry_confirm to agent 971 WABAs
#   ops/wa.sh submit-leadai-reminder-template [--dry-run]  Lead AI meeting reminder to every active assigned WABA
#   ops/wa.sh leadai-switch on|off|status   the Lead AI assistant's switch
#   ops/wa.sh leadai-test-numbers [digits…] numbers the assistant answers while it is off
#   ops/wa.sh leadai-alert-ids [ids…]       Bitrix users who also get booking/broker/handover alerts
#   ops/wa.sh set-leadai-office URL LAT LNG  the office's Google Maps short link and pin for Lead AI
#   ops/wa.sh qr-disable                  stop OpenWA + wa-qr; keep files; no autostart
#   ops/wa.sh qr-status                   OpenWA + wa-qr: state, restart policy, data on disk
#   ops/wa.sh load                        host load, RAM, disk, top containers

set -euo pipefail

HOST="root@187.127.123.235"
# The key is machine-specific: the Matloob profile used hostinger_codex; the Hp
# profile (2026-10-06) uses ~/.ssh/hostinger. WA_SSH_KEY overrides, otherwise
# the first path that exists wins, so the same script runs from both machines.
KEY="${WA_SSH_KEY:-}"
if [[ -z "$KEY" ]]; then
  for _k in "C:/Users/Matloob/.ssh/hostinger_codex" "${USERPROFILE//\\//}/.ssh/hostinger"; do
    [[ -f "$_k" ]] && KEY="$_k" && break
  done
fi
[[ -n "$KEY" ]] || { echo "wa.sh: no SSH key found (set WA_SSH_KEY)" >&2; exit 2; }
SITE="https://wa.srv1802669.hstgr.cloud"

# The server's host keys, pinned next to this script.
#
# These calls used to run with StrictHostKeyChecking=no, which accepts any key
# the far end offers — including a different one tomorrow. That is the whole of
# a man-in-the-middle: somebody between this laptop and the VPS answers as the
# VPS, and ssh says nothing. The private key is never disclosed by that (public
# key auth does not send it) but everything else is: what `sync` and `push`
# upload, what `sql` returns, and — the one that matters most here — what `sum`
# says a deployed file's checksum is. A deploy "verified" over an unauthenticated
# channel is not verified at all.
#
# accept-new rather than yes: a fresh clone with an empty file still works, but
# a key that *changes* is a fatal error rather than a shrug. The three keys in
# ops/known_hosts were captured from the server and matched against the ones
# already trusted in the operator's own ~/.ssh/known_hosts, recorded long before.
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/known_hosts"
# ssh.exe wants a Windows path; WSL /mnt/c/... cannot be written and stalls host-key updates.
KNOWN_HOSTS_SSH="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_SSH=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=20
  -o ServerAliveInterval=10
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$KNOWN_HOSTS_SSH"
)

# The only places anything is allowed to happen.
QR_DIR="/opt/a7-wa/wa-qr"
APP_DIR="/opt/a7-wa/deploy"
# OpenWA is a separate trial stack with its own compose file and its own root.
# Added deliberately rather than by loosening the check to /opt: this is a second
# named directory, not a wildcard, and everything below still refuses anything
# that is not provably inside one of them.
OPENWA_DIR="/opt/openwa-trial/OpenWA"

die() { echo "wa.sh: $*" >&2; exit 2; }

remote() { ssh.exe -i "$KEY" "${SSH_OPTS[@]}" "$HOST" "$@"; }

# The compose directory for a stack name, refusing anything else outright.
stack_dir() {
  case "${1:-}" in
    qr)     echo "$QR_DIR" ;;
    app)    echo "$APP_DIR" ;;
    openwa) echo "$OPENWA_DIR" ;;
    *)      die "unknown stack '${1:-}' — it is 'qr', 'app' or 'openwa'" ;;
  esac
}

# A container name, not a shell fragment. The whole point of this file is that
# what reaches the server is a name from a list, so `web; rm -rf /` is a
# rejected service name rather than two commands.
check_service() {
  [[ "${1:-}" =~ ^[a-z][a-z0-9_-]{0,30}$ ]] || die "'${1:-}' is not a service name"
}

check_count() {
  [[ "${1:-}" =~ ^[0-9]{1,5}$ ]] || die "'${1:-}' is not a number of lines"
}

# Inside one of the two deploy roots, and provably so — no `..`, no absolute
# escape, no characters a shell would read as anything other than a path.
#
# Two named roots rather than one, and never a prefix that could widen: `..` is
# refused before the prefix is trusted, so "/opt/a7-wa/../etc" cannot pass by
# starting with the right characters.
check_remote_path() {
  local p="${1:-}"
  [[ "$p" != *..* ]] || die "refusing a path containing '..': '$p'"
  [[ "$p" == /opt/a7-wa/* || "$p" == /opt/openwa-trial/* ]] ||
    die "refusing a path outside /opt/a7-wa and /opt/openwa-trial: '$p'"
  [[ "$p" =~ ^[A-Za-z0-9._/@-]+$ ]] || die "refusing unusual characters in: '$p'"
}

usage() { sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

cmd="${1:-}"
shift || true

case "$cmd" in

  ps)
    remote "cd $QR_DIR && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'; \
            echo '---'; \
            cd $APP_DIR && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'; \
            echo '--- openwa'; \
            cd $OPENWA_DIR && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'"
    ;;

  logs)
    dir=$(stack_dir "${1:-}"); check_service "${2:-}"; lines="${3:-120}"; check_count "$lines"
    remote "cd $dir && docker compose logs '$2' --tail $lines --no-log-prefix"
    ;;

  sql)
    dir=$(stack_dir "${1:-}")
    query="${2:-}"
    [[ -n "$query" ]] || die "sql needs a query"

    # OpenWA keeps its data in SQLite, not Postgres, so the same verb reaches a
    # different database there. Read-only is still the database's own answer and
    # not a regex's: `readonly: true` opens the file with SQLITE_OPEN_READONLY, so
    # sqlite itself refuses every write — including one smuggled in after a
    # semicolon — rather than a pattern deciding the query looked harmless.
    if [[ "${1:-}" == openwa ]]; then
      printf '%s' "$query" | remote "cd $dir && docker compose exec -T openwa-api sh -c '\
        exec node -e \"
          const Database = require(\\\"better-sqlite3\\\");
          const fs = require(\\\"fs\\\");
          const candidates = [process.env.DATABASE_NAME, \\\"/app/data/openwa.sqlite\\\", \\\"./data/openwa.sqlite\\\", \\\"/data/openwa.sqlite\\\"].filter(Boolean);
          const file = candidates.find(p => fs.existsSync(p));
          if (!file) { console.error(\\\"no sqlite file found in: \\\" + candidates.join(\\\", \\\")); process.exit(1); }
          const db = new Database(file, { readonly: true, fileMustExist: true });
          const sql = fs.readFileSync(0, \\\"utf8\\\");
          for (const row of db.prepare(sql).all()) console.log(Object.values(row).join(\\\"\t\\\"));
        \"'"
      exit 0
    fi

    # Read-only because the database says so, not because the query looked
    # harmless. --single-transaction puts both -c options in one transaction,
    # and a transaction marked READ ONLY refuses INSERT, UPDATE, DELETE, DROP
    # and everything else that writes — including a second statement smuggled
    # in after a semicolon.
    printf '%s' "$query" | remote "cd $dir && docker compose exec -T postgres sh -c '\
      exec psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v ON_ERROR_STOP=1 \
        --single-transaction -c \"SET TRANSACTION READ ONLY\" -f -'"
    ;;

  sum)
    check_remote_path "${1:-}"
    remote "md5sum '$1'"
    ;;

  get)
    path="${1:-/}"
    [[ "$path" == /* ]] || die "get takes a path beginning with /"
    url_ok='^[A-Za-z0-9._/?=&@-]+$'
    [[ "$path" =~ $url_ok ]] || die "refusing unusual characters in: '$path'"
    remote "curl -sk -o /dev/null -w 'HTTP %{http_code}  %{size_download} bytes\n' '$SITE$path'"
    ;;

  push)
    local_path="${1:-}"; remote_path="${2:-}"
    [[ -f "$local_path" ]] || die "no such local file: '$local_path'"
    check_remote_path "$remote_path"
    scp.exe -i "$KEY" "${SSH_OPTS[@]}" "$local_path" "$HOST:$remote_path"
    echo "pushed $(md5sum "$local_path" | cut -d' ' -f1)  ->  $remote_path"
    remote "md5sum '$remote_path'"
    ;;

  sync)
    # A whole directory, for the deploys that are more than one file. tar over
    # a pipe rather than rsync, which the server does not have.
    local_dir="${1:-}"; remote_dir="${2:-}"
    [[ -d "$local_dir" ]] || die "no such local directory: '$local_dir'"
    check_remote_path "$remote_dir"
    tar -cf - -C "$(dirname "$local_dir")" "$(basename "$local_dir")" \
      | remote "tar -xf - -C '$remote_dir' --overwrite"
    echo "synced $local_dir -> $remote_dir"
    # Said out loud, because a deploy that silently changed nothing is the
    # failure this project keeps having: three services reading one mount, and
    # one of them running last week's code.
    remote "find '$remote_dir/$(basename "$local_dir")' -name '*.js' | sort | xargs md5sum" | head -40
    ;;

  panel)
    # The Bitrix panel, deployed the way bitrix/deploy/deploy-panel.sh means to.
    #
    # That script uses rsync, which is not on every machine this repo is worked
    # from — it is absent from Git Bash on Windows, where it fails at the point
    # of copying and leaves the panel half-old. tar over a pipe is the fallback
    # CLAUDE.md names, and it is what this does.
    #
    # No arguments. Source and destination are both fixed, so this cannot be
    # pointed at anything else, and the only thing it can do is publish the
    # panel that lives in this repo.
    src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bitrix/public" && pwd)"
    [[ -d "$src" ]] || die "bitrix/public is missing"

    # --delete has no tar equivalent, so files removed from the repo are named
    # and removed on their own. A leftover nobody references is not harmless
    # here: /app/assets/bitrix-sso.js survived a folder move that way, and
    # install.html went on loading the stale copy for weeks.
    stale=""
    for f in "$@"; do
      [[ "$f" =~ ^[A-Za-z0-9._/-]+$ ]] || die "refusing an unusual name: '$f'"
      [[ "$f" != *..* ]]               || die "refusing '..' in: '$f'"
      stale="$stale /opt/a7-wa/panel/$f"
    done

    tar -cf - -C "$src" . | remote "tar -xf - -C /opt/a7-wa/panel --overwrite"
    [[ -z "$stale" ]] || remote "rm -f $stale && echo 'removed:$stale'"
    remote "chown -R www-data:www-data /opt/a7-wa/panel && nginx -t && systemctl reload nginx"
    echo "published $src -> /opt/a7-wa/panel"
    ;;

  build)
    # The service is optional, and leaving it off is the documented practice:
    # `web`, `worker` and `beat` build separately, so naming one leaves the other
    # two on their old images — which is how three services end up running three
    # versions, and it is easy to miss because webhook processing happens in
    # `worker` while everything reached by hand answers from `web`.
    dir=$(stack_dir "${1:-}")
    if [[ -n "${2:-}" ]]; then
      check_service "$2"
      remote "cd $dir && docker compose build '$2' 2>&1 | tail -3"
    else
      remote "cd $dir && docker compose build 2>&1 | tail -3"
    fi
    ;;

  up)
    # `up -d` and not `restart`, because a rebuilt image only reaches a
    # container that is recreated. `restart` starts the old one again.
    #
    # With no service it recreates the whole app stack, which is the deploy:
    # `web`, `worker`, `worker-leadai` and `beat` are separate containers, and
    # one left out keeps running the old code. worker-leadai, the only
    # consumer of the Lead AI queue, is the one nobody would notice. The QR
    # stacks are stopped on purpose (qr-disable), so they still need a service.
    dir=$(stack_dir "${1:-}")
    if [[ -n "${2:-}" ]]; then
      check_service "$2"
      remote "cd $dir && docker compose up -d '$2' 2>&1 | tail -3"
    elif [[ "$1" == app ]]; then
      remote "cd $dir && docker compose up -d 2>&1 | tail -20"
    else
      die "up $1 needs a service; only the app stack is recreated whole"
    fi
    ;;

  openwa-state)
    [[ $# -eq 0 ]] || die "openwa-state takes no arguments"
    remote "set -eu; cd $OPENWA_DIR; \
      cid=\$(docker compose ps -q openwa-api); test -n \"\$cid\"; \
      image=\$(docker inspect -f '{{.Image}}' \"\$cid\"); \
      docker inspect -f 'container-image={{.Image}} state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \"\$cid\"; \
      docker image inspect -f 'image-id={{.Id}} image-digests={{json .RepoDigests}} created={{.Created}}' \"\$image\"; \
      readiness=\$(docker exec \"\$cid\" node -e 'const http=require(\"http\");const request=http.get(\"http://localhost:2785/api/health/ready\",response=>{console.log(response.statusCode);response.resume()});request.on(\"error\",()=>process.exit(1))'); \
      echo readiness-http=\$readiness; \
      sync=\$(docker exec \"\$cid\" sh -c 'if [ \"\${DATABASE_SYNCHRONIZE:-}\" = true ] || grep -qx \"DATABASE_SYNCHRONIZE=true\" /app/data/.env.generated 2>/dev/null; then echo true; else echo false; fi'); \
      echo database-synchronize=\$sync; \
      docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'; \
      df -h /opt/openwa-trial /var/lib/docker/volumes/openwa_openwa-data/_data | tail -n +2"
    ;;

  openwa-cold-backup)
    [[ $# -eq 0 ]] || die "openwa-cold-backup takes no arguments"
    remote "set -eu; cd $OPENWA_DIR; \
      docker compose stop openwa-api; \
      running=\$(docker compose ps --status running -q openwa-api); test -z \"\$running\"; \
      test -f /var/lib/docker/volumes/openwa_openwa-data/_data/openwa.sqlite; \
      mkdir -p /opt/openwa-trial/backups; \
      stamp=\$(date -u +%Y%m%dT%H%M%SZ); \
      archive=/opt/openwa-trial/backups/openwa-data-\$stamp.tar.gz; \
      tar -C /var/lib/docker/volumes/openwa_openwa-data/_data -czf \"\$archive\" .; \
      echo backup=\$(basename \"\$archive\"); \
      md5sum \"\$archive\"; \
      sqlite_count=\$(tar -tzf \"\$archive\" | grep -Ec '(^|/)openwa.sqlite$' || true); \
      test \"\$sqlite_count\" -eq 1; echo sqlite=present"
    ;;

  openwa-inspect-asma-backup)
    [[ $# -eq 0 ]] || die "openwa-inspect-asma-backup takes no arguments"
    remote "set -eu; cd $OPENWA_DIR; \
      archive=/opt/openwa-trial/backups/openwa-data-20260808T074558Z.tar.gz; \
      tool=$OPENWA_DIR/restore-asma.js; \
      test -f \"\$archive\"; test -f \"\$tool\"; \
      tmp=\$(mktemp -d /opt/openwa-trial/asma-inspect.XXXXXX); \
      trap 'rm -rf \"\$tmp\"' EXIT; \
      tar -xzf \"\$archive\" -C \"\$tmp\"; test -f \"\$tmp/openwa.sqlite\"; \
      image=\$(docker compose images -q openwa-api | head -1); test -n \"\$image\"; \
      docker run --rm --network none --read-only \
        -v \"\$tmp/openwa.sqlite:/restore/openwa.sqlite:ro\" \
        -v \"\$tool:/app/restore-asma.js:ro\" \
        -w /app --entrypoint node \"\$image\" \
        /app/restore-asma.js inspect /restore/openwa.sqlite"
    ;;

  openwa-restore-asma)
    [[ $# -eq 0 ]] || die "openwa-restore-asma takes no arguments"
    remote "set -eu; cd $OPENWA_DIR; \
      archive=/opt/openwa-trial/backups/openwa-data-20260808T074558Z.tar.gz; \
      tool=$OPENWA_DIR/restore-asma.js; \
      volume=/var/lib/docker/volumes/openwa_openwa-data/_data; \
      test -f \"\$archive\"; test -f \"\$tool\"; test -f \"\$volume/openwa.sqlite\"; \
      image=\$(docker compose images -q openwa-api | head -1); test -n \"\$image\"; \
      tmp=\$(mktemp -d /opt/openwa-trial/asma-restore.XXXXXX); \
      started=0; \
      cleanup() { rm -rf \"\$tmp\"; if [ \"\$started\" -eq 0 ]; then docker compose start openwa-api >/dev/null; fi; }; \
      trap cleanup EXIT; \
      tar -xzf \"\$archive\" -C \"\$tmp\"; test -f \"\$tmp/openwa.sqlite\"; \
      docker compose stop openwa-api; \
      running=\$(docker compose ps --status running -q openwa-api); test -z \"\$running\"; \
      mkdir -p /opt/openwa-trial/backups; \
      stamp=\$(date -u +%Y%m%dT%H%M%SZ); \
      cold=/opt/openwa-trial/backups/openwa-data-\$stamp.tar.gz; \
      tar -C \"\$volume\" -czf \"\$cold\" .; \
      echo backup=\$(basename \"\$cold\"); md5sum \"\$cold\"; \
      sqlite_count=\$(tar -tzf \"\$cold\" | grep -Ec '(^|/)openwa.sqlite\$' || true); \
      test \"\$sqlite_count\" -eq 1; echo sqlite=present; \
      docker run --rm --network none --read-only \
        -v \"\$volume:/live:rw\" \
        -v \"\$tmp/openwa.sqlite:/restore/openwa.sqlite:ro\" \
        -v \"\$tool:/app/restore-asma.js:ro\" \
        -w /app --entrypoint node \"\$image\" \
        /app/restore-asma.js restore /live/openwa.sqlite /restore/openwa.sqlite; \
      docker compose start openwa-api >/dev/null; started=1; \
      for n in 1 2 3 4 5 6; do \
        cid=\$(docker compose ps -q openwa-api); \
        health=\$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \"\$cid\"); \
        [ \"\$health\" = healthy ] && break; sleep 5; \
      done; \
      echo api-health=\$health; test \"\$health\" = healthy"
    ;;

  openwa-verify-asma-restore)
    [[ $# -eq 0 ]] || die "openwa-verify-asma-restore takes no arguments"
    verify_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/openwa/verify-asma-restore.py"
    [[ -f "$verify_script" ]] || die "missing ops/openwa/verify-asma-restore.py"
    encoded=$(base64 -w0 < "$verify_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  openwa-browser-verify-asma)
    [[ $# -eq 0 ]] || die "openwa-browser-verify-asma takes no arguments"
    verify_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/openwa/verify-asma-dashboard.js"
    [[ -f "$verify_script" ]] || die "missing ops/openwa/verify-asma-dashboard.js"
    encoded=$(base64 -w0 < "$verify_script")
    printf '%s' "$encoded" | remote "cd $OPENWA_DIR && base64 -d | docker compose exec -T openwa-api node -"
    ;;

  openwa-stop-restored-asma)
    [[ $# -eq 0 ]] || die "openwa-stop-restored-asma takes no arguments"
    remote "cd $OPENWA_DIR && docker compose exec -T openwa-api node -e '
      const id = \"e209881a-0aa3-4463-849f-ff0ed37144b5\";
      const key = process.env.API_MASTER_KEY || process.env.API_KEY;
      if (!key) throw new Error(\"master API key is unavailable\");
      fetch(\"http://127.0.0.1:2785/api/sessions/\" + id + \"/stop\", {
        method: \"POST\", headers: { \"X-API-Key\": key }
      }).then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(\"stop returned HTTP \" + response.status);
        if (body.id !== id || body.name !== \"asma\" || body.status !== \"disconnected\") {
          throw new Error(\"stop response identity/status assertion failed\");
        }
        console.log(\"restored-asma-stop=PASS\");
        console.log(\"restored-status=disconnected\");
      }).catch(error => { console.error(error.message); process.exit(1); });
    '"
    ;;

  openwa-arm-restored-asma)
    [[ $# -eq 0 ]] || die "openwa-arm-restored-asma takes no arguments"
    remote "set -eu; cd $OPENWA_DIR; \
      running=\$(docker compose ps --status running -q openwa-api); test -z \"\$running\"; \
      volume=/var/lib/docker/volumes/openwa_openwa-data/_data; \
      tool=$OPENWA_DIR/arm-asma-manual-start.js; \
      test -f \"\$volume/openwa.sqlite\"; test -f \"\$tool\"; \
      image=openwa-openwa-api; docker image inspect \"\$image\" >/dev/null; \
      docker run --rm --network none --read-only \
        -v \"\$volume:/live:rw\" -v \"\$tool:/app/arm-asma-manual-start.js:ro\" \
        -w /app --entrypoint node \"\$image\" \
        /app/arm-asma-manual-start.js /live/openwa.sqlite"
    ;;

  openwa-delete-javeria-one-chat)
    [[ $# -eq 0 ]] || die "openwa-delete-javeria-one-chat takes no arguments"
    delete_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/openwa/delete-javeria-one-chat.js"
    [[ -f "$delete_script" ]] || die "missing ops/openwa/delete-javeria-one-chat.js"
    encoded=$(base64 -w0 < "$delete_script")
    printf '%s' "$encoded" | remote "cd $OPENWA_DIR && base64 -d | docker compose exec -T openwa-api node -"
    ;;

  openwa-reset-restored-asma)
    [[ $# -eq 0 ]] || die "openwa-reset-restored-asma takes no arguments"
    remote "cd $OPENWA_DIR && docker compose exec -T openwa-api node -e '
      const id = \"e209881a-0aa3-4463-849f-ff0ed37144b5\";
      const key = process.env.API_MASTER_KEY || process.env.API_KEY;
      if (!key) throw new Error(\"master API key is unavailable\");
      fetch(\"http://127.0.0.1:2785/api/sessions/\" + id + \"/reset-profile\", {
        method: \"POST\", headers: { \"X-API-Key\": key }
      }).then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(\"reset returned HTTP \" + response.status);
        if (body.id !== id || body.name !== \"asma\" || body.status !== \"disconnected\" || body.engineLoaded !== false) {
          throw new Error(\"reset response identity/status assertion failed\");
        }
        console.log(\"restored-asma-profile-reset=PASS\");
        console.log(\"restored-status=disconnected\");
        console.log(\"restored-engine-loaded=false\");
      }).catch(error => { console.error(error.message); process.exit(1); });
    '"
    ;;

  openwa-force-recreate)
    [[ $# -eq 0 ]] || die "openwa-force-recreate takes no arguments"
    # Keep the redis profile up: Conversation Health + BullMQ need openwa-redis on the network.
    remote "cd $OPENWA_DIR && docker compose --profile redis up -d redis && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -8"
    ;;

  qr-disable)
    # Stop Linked QR (OpenWA) and Official wa-qr. Volumes and bind-mount data
    # stay on disk. restart=no so a reboot does not bring Chromium back.
    # Chromium often ignores SIGTERM; compose stop then kill if it hangs.
    [[ $# -eq 0 ]] || die "qr-disable takes no arguments"
    remote "set -eu
      halt() {
        dir=\$1
        extra=\$2
        cd \"\$dir\"
        cids=\$(docker compose \$extra ps -aq || true)
        if [ -n \"\$cids\" ]; then docker update --restart=no \$cids >/dev/null || true; fi
        docker compose \$extra stop || true
        running=\$(docker compose \$extra ps --status running -q || true)
        if [ -n \"\$running\" ]; then docker compose \$extra kill || true; fi
        running=\$(docker compose \$extra ps --status running -q || true)
        if [ -n \"\$running\" ]; then docker kill \$running || true; fi
        leftover=\$(docker compose \$extra ps --status running -q || true)
        test -z \"\$leftover\"
      }
      halt $OPENWA_DIR '--profile redis'
      test -f /var/lib/docker/volumes/openwa_openwa-data/_data/openwa.sqlite
      echo openwa=stopped data=kept
      cd $OPENWA_DIR && docker compose --profile redis ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'
      halt $QR_DIR ''
      test -d $QR_DIR/data
      echo wa-qr=stopped data=kept
      cd $QR_DIR && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'
    "
    ;;

  qr-status)
    [[ $# -eq 0 ]] || die "qr-status takes no arguments"
    remote "set -eu
      echo '=== openwa ==='
      cd $OPENWA_DIR
      docker compose --profile redis ps -a --format '{{.Service}}\t{{.State}}\t{{.Status}}'
      for c in \$(docker compose --profile redis ps -aq); do
        docker inspect -f '{{.Name}} {{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}' \"\$c\"
      done
      if [ -f /var/lib/docker/volumes/openwa_openwa-data/_data/openwa.sqlite ]; then echo sqlite=kept; else echo sqlite=MISSING; fi
      echo '=== wa-qr ==='
      cd $QR_DIR
      docker compose ps -a --format '{{.Service}}\t{{.State}}\t{{.Status}}'
      for c in \$(docker compose ps -aq); do
        docker inspect -f '{{.Name}} {{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}' \"\$c\"
      done
      if [ -d $QR_DIR/data ]; then echo wa-qr-data=kept; else echo wa-qr-data=MISSING; fi
      echo '=== load ==='
      uptime
    "
    ;;

  load)
    [[ $# -eq 0 ]] || die "load takes no arguments"
    remote "set -eu
      echo '=== host ==='
      nproc
      uptime
      free -h
      df -hP /
      echo '=== docker ==='
      docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}'
    "
    ;;

  unlock)
    # Chromium leaves a SingletonLock behind when its container is killed rather
    # than stopped, and the next start refuses the profile: "already in use by
    # another Chromium process on another computer". Only the three lock files
    # go — the session data beside them is what stops every linked phone having
    # to scan again.
    remote "cd $QR_DIR && docker compose stop app >/dev/null 2>&1; \
            find data -maxdepth 4 -name 'Singleton*' -print -delete; \
            docker compose up -d app 2>&1 | tail -2"
    ;;

  restart)
    dir=$(stack_dir "${1:-}")
    shift
    [[ $# -gt 0 ]] || die "restart needs at least one service"
    for s in "$@"; do check_service "$s"; done
    remote "cd $dir && docker compose restart $*"
    ;;

  migrate)
    # Apply pending Django migrations on the live app stack. Fixed command —
    # no passthrough args — so this cannot become arbitrary manage.py execution.
    remote "cd $APP_DIR && docker compose exec -T web python manage.py migrate --noinput"
    ;;

  django-check)
    # The two CLAUDE.md insists on after any migration work. Fixed, not a
    # passthrough — `manage.py <anything>` would be arbitrary execution again.
    remote "cd $APP_DIR && docker compose exec -T web python manage.py makemigrations --check --dry-run; \
            echo '---'; \
            cd $APP_DIR && docker compose exec -T web python manage.py showmigrations"
    ;;

  migrate-new-image)
    # Migrations from the image just BUILT, before `up`. `migrate` above runs in
    # the running web container, i.e. the old code, which cannot see a migration
    # that is new in this build, while the new code must not start before its
    # tables exist. So: a one-off container of the new image — no ports, nothing
    # else started, removed afterwards.
    [[ $# -eq 0 ]] || die "migrate-new-image takes no arguments"
    remote "cd $APP_DIR && docker compose run --rm --no-deps -T web python manage.py migrate --noinput 2>&1 | tail -25"
    ;;

  leadai-tests)
    # The Lead AI test suite in a one-off container of the image just built, on
    # the live Postgres server but inside Django's own throwaway test_<db>
    # database. Every way out is shut twice, in a7wa/settings_livetest.py and
    # in the environment here (Celery reads CELERY_BROKER_URL from the
    # environment first), so a test that forgets a fake fails instead of
    # reaching Redis, the workers, the gateway, Bitrix or OpenAI.
    [[ $# -eq 0 ]] || die "leadai-tests takes no arguments"
    remote "cd $APP_DIR && docker compose run --rm --no-deps -T \
      -e CELERY_BROKER_URL=memory:// -e CELERY_RESULT_BACKEND=cache+memory:// -e REDIS_URL=redis://127.0.0.1:1/0 \
      -e OPENAI_API_KEY= -e LEADAI_OPENAI_API_KEY= -e BITRIX_WEBHOOK_URL= -e ALOTS_API_KEY=test-key \
      web python manage.py test apps.leadai --settings=a7wa.settings_livetest --noinput -v 1 2>&1 | tail -40"
    ;;

  deploy-villa-nova2)
    [[ $# -eq 0 ]] || die "deploy-villa-nova2 takes no arguments"
    deploy_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/deploy-villa-nova2.py"
    [[ -f "$deploy_script" ]] || die "missing ops/catalog/deploy-villa-nova2.py"
    encoded=$(base64 -w0 < "$deploy_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  retry-villa-nova2-failed)
    [[ $# -eq 0 ]] || die "retry-villa-nova2-failed takes no arguments"
    retry_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/retry-villa-nova2-failed.py"
    [[ -f "$retry_script" ]] || die "missing ops/catalog/retry-villa-nova2-failed.py"
    encoded=$(base64 -w0 < "$retry_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;


  add-dubai10wbx-numbers)
    [[ $# -eq 0 ]] || die "add-dubai10wbx-numbers takes no arguments"
    add_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/add-dubai10wbx-numbers.py"
    [[ -f "$add_script" ]] || die "missing ops/catalog/add-dubai10wbx-numbers.py"
    encoded=$(base64 -w0 < "$add_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  label-oct8-wbx-numbers)
    # Names the Oct-8 WBBOX numbers already synced into Official (Coastline / Blue Brick).
    [[ $# -eq 0 ]] || die "label-oct8-wbx-numbers takes no arguments"
    label_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/label-oct8-wbx-numbers.py"
    [[ -f "$label_script" ]] || die "missing ops/catalog/label-oct8-wbx-numbers.py"
    encoded=$(base64 -w0 < "$label_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  keep-sheet-official-numbers)
    [[ $# -eq 0 ]] || die "keep-sheet-official-numbers takes no arguments"
    keep_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/keep-sheet-official-numbers.py"
    [[ -f "$keep_script" ]] || die "missing ops/catalog/keep-sheet-official-numbers.py"
    encoded=$(base64 -w0 < "$keep_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  assign-18-971-44)
    [[ $# -eq 0 ]] || die "assign-18-971-44 takes no arguments"
    assign_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/assign-18-971-44.py"
    [[ -f "$assign_script" ]] || die "missing ops/catalog/assign-18-971-44.py"
    encoded=$(base64 -w0 < "$assign_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  replay-ignored-flat-outbound)
    # One-shot: re-queue Alots flat body webhooks ignored for missing phone_number_id.
    [[ $# -eq 0 ]] || die "replay-ignored-flat-outbound takes no arguments"
    replay_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gateway/replay-ignored-flat-outbound.py"
    [[ -f "$replay_script" ]] || die "missing ops/gateway/replay-ignored-flat-outbound.py"
    encoded=$(base64 -w0 < "$replay_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;




  retry-failed-audio)
    [[ $# -eq 0 ]] || die "retry-failed-audio takes no arguments"
    retry_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/retry-failed-audio.py"
    [[ -f "$retry_script" ]] || die "missing ops/catalog/retry-failed-audio.py"
    encoded=$(base64 -w0 < "$retry_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  sync-all-templates)
    [[ $# -eq 0 ]] || die "sync-all-templates takes no arguments"
    sync_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/sync-all-templates.py"
    [[ -f "$sync_script" ]] || die "missing ops/catalog/sync-all-templates.py"
    encoded=$(base64 -w0 < "$sync_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  retry-template-sync-failed)
    [[ $# -eq 0 ]] || die "retry-template-sync-failed takes no arguments"
    retry_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/retry-template-sync-failed.py"
    [[ -f "$retry_script" ]] || die "missing ops/catalog/retry-template-sync-failed.py"
    encoded=$(base64 -w0 < "$retry_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;


  explain-template-count-gap)
    [[ $# -eq 0 ]] || die "explain-template-count-gap takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/explain-template-count-gap.py"
    [[ -f "$script" ]] || die "missing ops/catalog/explain-template-count-gap.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;





  probe-openai-key)
    # The OpenAI key the live web container uses: set or not, an 8-hex SHA-256
    # fingerprint, the model, and how a one-token call answered. Never the key.
    [[ $# -eq 0 ]] || die "probe-openai-key takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-openai-key.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-openai-key.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-leadai-notify)
    # The Lead AI alerts' Bitrix path end to end: ONE test notification to
    # Bitrix user 2311 (the owner) only, its duplicate refused, and the tool's
    # refusal of a wrong / missing / old signature and of a GET. No secret shown.
    [[ $# -eq 0 ]] || die "probe-leadai-notify takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-leadai-notify.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-leadai-notify.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-leadai-key)
    # The Lead AI's own key (LEADAI_OPENAI_API_KEY) as a NEW container reads it
    # from .env: set or not, its 8-hex fingerprint, and how one 1-token call to
    # the Lead AI model answered. A one-off container, removed after. Never the key.
    [[ $# -eq 0 ]] || die "probe-leadai-key takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-leadai-key.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-leadai-key.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose run --rm --no-deps -T web python - 2>&1 | grep -v '^Container\\|Creating\\|Created'"
    ;;

  probe-bitrix-methods)
    # Which CRM activity/to-do REST methods the backend's webhook may call.
    # Read-only REST method "methods"; never prints the webhook or its token.
    [[ $# -eq 0 ]] || die "probe-bitrix-methods takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-bitrix-methods.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-bitrix-methods.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-bitrix-scope)
    # The permission scopes of the backend's Bitrix webhook (may it notify?).
    # Read-only REST method "scope"; never prints the webhook or its token.
    [[ $# -eq 0 ]] || die "probe-bitrix-scope takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-bitrix-scope.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-bitrix-scope.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  set-leadai-openai-key)
    # The OpenAI key that ONLY the Lead AI assistant uses, written as
    # LEADAI_OPENAI_API_KEY from ONE local file. The key travels on stdin
    # (never argv, never echoed). OPENAI_API_KEY, which everything else uses,
    # is checked before and after and the write is refused if it would change.
    # No container is recreated here: afterwards, `ops/wa.sh up app web` and
    # `ops/wa.sh up app worker-leadai` (env_file is read when a container is
    # created). `probe-leadai-key` checks the new key from a fresh container.
    [[ $# -eq 1 ]] || die "set-leadai-openai-key takes one local file that holds the key"
    [[ -f "$1" ]] || die "no such local file: '$1'"
    key=$(tr -d '\r\n' < "$1")
    [[ "$key" =~ ^sk-[A-Za-z0-9_-]{20,}$ && ${#key} -le 400 ]] || die "that file does not hold an OpenAI key"
    printf '%s' "$key" | remote "set -eu
      f=$APP_DIR/.env
      [ -f \"\$f\" ] || { echo 'missing $APP_DIR/.env'; exit 1; }
      NEWKEY=''
      IFS= read -r NEWKEY || true
      case \"\$NEWKEY\" in sk-*) ;; *) echo 'no key arrived on stdin'; exit 1 ;; esac
      main_before=\$(grep '^OPENAI_API_KEY=' \"\$f\" | sha256sum)
      tmp=\$(mktemp \"\$f.XXXXXX\")
      NEWKEY=\"\$NEWKEY\" awk '/^LEADAI_OPENAI_API_KEY=/ { if (!seen) { print \"LEADAI_OPENAI_API_KEY=\" ENVIRON[\"NEWKEY\"]; seen = 1 } next } { print } END { if (!seen) print \"LEADAI_OPENAI_API_KEY=\" ENVIRON[\"NEWKEY\"] }' \"\$f\" > \"\$tmp\"
      chmod --reference=\"\$f\" \"\$tmp\"
      chown --reference=\"\$f\" \"\$tmp\"
      [ \"\$(grep '^OPENAI_API_KEY=' \"\$tmp\" | sha256sum)\" = \"\$main_before\" ] || { rm -f \"\$tmp\"; echo 'refusing: OPENAI_API_KEY would change'; exit 1; }
      mv \"\$tmp\" \"\$f\"
      echo \"LEADAI_OPENAI_API_KEY lines: \$(grep -c '^LEADAI_OPENAI_API_KEY=' \"\$f\")\"
      echo \"lead ai key fingerprint: \$(grep '^LEADAI_OPENAI_API_KEY=' \"\$f\" | head -1 | cut -d= -f2- | tr -d '\\r\\n' | sha256sum | cut -c1-8)\"
      echo \"main key fingerprint, unchanged: \$(grep '^OPENAI_API_KEY=' \"\$f\" | head -1 | cut -d= -f2- | tr -d '\\r\\n' | sha256sum | cut -c1-8)\"
    "
    ;;



  probe-send-404)
    [[ $# -eq 0 ]] || die "probe-send-404 takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-send-404.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-send-404.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-nabiha-500)
    [[ $# -eq 0 ]] || die "probe-nabiha-500 takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-nabiha-500.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-nabiha-500.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;


  probe-template-header-media)
    # Forced-login checks of the header-media route: the refusals, then one
    # real sample upload, so one throwaway handle is minted through the gateway.
    [[ $# -eq 0 ]] || die "probe-template-header-media takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-template-header-media.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-template-header-media.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;




  probe-crm-entities)
    # Read-only: the CRM-leads campaign code in the live image resolves
    # deal / contact / lead rows to the right CRM id. Nothing is sent.
    [[ $# -eq 0 ]] || die "probe-crm-entities takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-crm-entities.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-crm-entities.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR &&       base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-media-template-path)
    # Read-only: is the Meta Graph token set, is the alots panel session alive —
    # the two ways an IMAGE/VIDEO template sample handle can be minted. No secrets.
    [[ $# -eq 0 ]] || die "probe-media-template-path takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-media-template-path.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-media-template-path.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR &&       base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-gateway-upload)
    # Steps 1+2 of the icpaas.in PDF with our own API key: one upload session,
    # one 70-byte PNG. Proves whether the gateway can mint the sample handle.
    # No template is created and nothing is sent. Never prints the key.
    [[ $# -eq 0 ]] || die "probe-gateway-upload takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-gateway-upload.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-gateway-upload.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR &&       base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-gateway-media-template)
    # One throwaway IMAGE-header template (UTILITY, hidden from the panel at
    # once) on WABA 1426351832653450, through the real header-media and create
    # routes: proves a handle minted through the gateway is one Meta accepts.
    [[ $# -eq 0 ]] || die "probe-gateway-media-template takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-gateway-media-template.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-gateway-media-template.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-gateway-media-template-status)
    # Read-only: Meta's current status of the throwaway templates the probe
    # above created (PENDING -> APPROVED/REJECTED). Nothing is sent.
    [[ $# -eq 0 ]] || die "probe-gateway-media-template-status takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-gateway-media-template-status.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-gateway-media-template-status.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-crm-header-media)
    # Signed like a7_lead_wa.php: the refusals, one real 1x1 PNG uploaded for
    # 971524077268, then the token through send_from_leads in a rolled-back
    # transaction with Celery stubbed. Nothing is sent.
    [[ $# -eq 0 ]] || die "probe-crm-header-media takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-crm-header-media.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-crm-header-media.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-dump-inbox-sources)
    # Read-only: the files the 2026-10 visibility change touched, exactly as the
    # running web image has them (base64), to bring a local checkout level.
    [[ $# -eq 0 ]] || die "probe-dump-inbox-sources takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-dump-inbox-sources.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-dump-inbox-sources.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-backend-md5)
    # Read-only: md5 (line endings normalised) of every source file in the
    # running web image, to diff a local checkout against what is live.
    [[ $# -eq 0 ]] || die "probe-backend-md5 takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-backend-md5.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-backend-md5.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-list-channels)
    # Read-only: Alots channel list vs catalog_wabanumber (find numbers not yet added).
    [[ $# -eq 0 ]] || die "probe-list-channels takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-list-channels.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-list-channels.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-numbers-roster)
    # Read-only: CSV of every Official number and who it is assigned to.
    [[ $# -eq 0 ]] || die "probe-numbers-roster takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-numbers-roster.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-numbers-roster.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-lead-ai-fixture)
    # Creates ONE synthetic Lead AI chat (customer 999000000001, "ZZ Lead AI
    # test (delete)") for a browser test of the Lead AI screen. No message
    # signals, closed window, nothing sent. Undo: probe-lead-ai-cleanup.
    [[ $# -eq 0 ]] || die "probe-lead-ai-fixture takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-lead-ai-fixture.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-lead-ai-fixture.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-lead-ai-cleanup)
    # Deletes the synthetic chat probe-lead-ai-fixture made, and nothing else.
    [[ $# -eq 0 ]] || die "probe-lead-ai-cleanup takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-lead-ai-cleanup.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-lead-ai-cleanup.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-lead-ai-flow)
    # Checks the Lead AI routing rules on the live code and data, inside ONE
    # transaction that is always rolled back: campaign task and live events
    # replaced, no message made, nothing sent, nothing kept.
    [[ $# -eq 0 ]] || die "probe-lead-ai-flow takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-lead-ai-flow.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-lead-ai-flow.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  leadai-eval|leadai-eval-draft)
    # The Lead AI prompt against the real model on the scripted chats of
    # apps/leadai/management/commands/leadai_eval.py. Sends nothing and stores
    # nothing (every database query is refused while it runs). Options:
    # --only <scenario id or part of one>, --repeat 1-10, --show, --list.
    # leadai-eval runs the deployed image (web); leadai-eval-draft runs in beat,
    # whose /app is the build context, so pushed files are judged before a build.
    service=web
    [[ "$cmd" == leadai-eval-draft ]] && service=beat
    args=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --only)
          [[ "${2:-}" =~ ^[a-z0-9-]{1,40}$ ]] || die "--only takes a scenario id (lowercase letters, digits, '-')"
          args+=(--only "$2"); shift 2 ;;
        --repeat)
          [[ "${2:-}" =~ ^([1-9]|10)$ ]] || die "--repeat takes 1 to 10"
          args+=(--repeat "$2"); shift 2 ;;
        --show|--list) args+=("$1"); shift ;;
        *) die "leadai-eval takes --only ID, --repeat N, --show and --list" ;;
      esac
    done
    remote "cd $APP_DIR && docker compose exec -T $service python manage.py leadai_eval ${args[*]:-} 2>&1 | tail -200"
    ;;

  probe-leadai-turn)
    # Three real Lead AI assistant turns (book, move, STOP) on the live code,
    # database and Lead AI key, inside ONE transaction that is always rolled
    # back: sends faked, live events faked, tasks never queued, nothing kept.
    # Only the OpenAI calls leave (synthetic text, a few thousand tokens).
    [[ $# -eq 0 ]] || die "probe-leadai-turn takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-leadai-turn.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-leadai-turn.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-c16-credit)
    # C16: poll the gateway wallet, reclaim exhausted credit rows, hit /api/gateway/credit/.
    # Prints only out/counts — never the balance figure.
    [[ $# -eq 0 ]] || die "probe-c16-credit takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-c16-credit.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-c16-credit.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  test)
    # Unit tests in a one-off container of the live web image, on Django's
    # throwaway test database. The image has no pytest, so this is manage.py
    # test with the label fixed from the path — not a passthrough. Same locks
    # as leadai-tests: the broker, Redis, Bitrix and OpenAI stay pointed away
    # from production. Build first if the test file is new in the image.
    target="${1:-apps}"
    [[ "$target" =~ ^apps(/[a-z_]+(/tests(/test_[a-z0-9_]+\.py)?)?)?$ ]] ||
      die "test takes a path like apps/catalog/tests/test_templates.py"
    module="${target%.py}"
    module="${module//\//.}"
    [[ "$module" =~ ^apps(\.[a-z_]+(\.tests(\.test_[a-z0-9_]+)?)?)?$ ]] ||
      die "refusing test module '$module'"
    remote "cd $APP_DIR && docker compose run --rm --no-deps -T \
      -e CELERY_BROKER_URL=memory:// -e CELERY_RESULT_BACKEND=cache+memory:// -e REDIS_URL=redis://127.0.0.1:1/0 \
      -e OPENAI_API_KEY= -e LEADAI_OPENAI_API_KEY= -e BITRIX_WEBHOOK_URL= -e ALOTS_API_KEY=test-key \
      web python manage.py test '$module' --settings=a7wa.settings_livetest --noinput -v 1"
    ;;

  agent-reports-deploy)
    # Fixed deploy of the Sales/TS Agent Daily Reports app. Paths and compose
    # file are hard-coded under /opt/a7-wa/agent-reports — no caller-chosen
    # remote destination. Nginx gets one new location (^~ /agent-reports/) if
    # missing; the rest of a7-wa.conf is untouched.
    [[ $# -eq 0 ]] || die "agent-reports-deploy takes no arguments"
    src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../agent-reports" && pwd)"
    [[ -d "$src" ]] || die "agent-reports/ is missing"
    [[ -f "$src/deploy/docker-compose.yml" ]] || die "agent-reports/deploy/docker-compose.yml missing"
    [[ -f "$src/.env" ]] || die "agent-reports/.env missing — copy from .env.example and fill secrets"

    remote "mkdir -p /opt/a7-wa/agent-reports"
    tar --exclude='.venv' --exclude='__pycache__' --exclude='storage' \
        --exclude='*.db' --exclude='.pytest_cache' \
        -cf - -C "$(dirname "$src")" "$(basename "$src")" \
      | remote "tar -xf - -C /opt/a7-wa --overwrite"
    scp.exe -i "$KEY" "${SSH_OPTS[@]}" "$src/.env" "$HOST:/opt/a7-wa/agent-reports/.env"
    remote "cd /opt/a7-wa/agent-reports/deploy && docker compose build 2>&1 | tail -20"
    remote "cd /opt/a7-wa/agent-reports/deploy && docker compose up -d 2>&1 | tail -20"
    remote "cd /opt/a7-wa/agent-reports/deploy && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'"

    # Nginx: always re-run fix_nginx.py so /agent-reports/ lands in the :443
    # server (an earlier awk install mistakenly targeted the :80 redirect block).
    remote "python3 /opt/a7-wa/agent-reports/deploy/fix_nginx.py && nginx -t && systemctl reload nginx"
    remote "curl -sk -H 'Host: wa.srv1802669.hstgr.cloud' -o /dev/null -w 'health %{http_code}\n' https://127.0.0.1/agent-reports/health; curl -sk -o /dev/null -w 'local8091 %{http_code}\n' http://127.0.0.1:8091/health"
    echo "deployed agent-reports → https://wa.srv1802669.hstgr.cloud/agent-reports/"
    echo "Bitrix left menu iframe URL: https://wa.srv1802669.hstgr.cloud/agent-reports/"
    ;;

  agent-reports-check)
    [[ $# -eq 0 ]] || die "agent-reports-check takes no arguments"
    remote "cd /opt/a7-wa/agent-reports/deploy && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'"
    remote "grep -n agent-reports /etc/nginx/conf.d/a7-wa.conf | head -20"
    remote "curl -sk -o /dev/null -w 'local8091 %{http_code}\n' http://127.0.0.1:8091/health"
    remote "curl -sk -H 'Host: wa.srv1802669.hstgr.cloud' -o /tmp/ar-n.json -w 'nginx-host %{http_code}\n' https://127.0.0.1/agent-reports/health; head -c 300 /tmp/ar-n.json; echo"
    remote "curl -sk -o /tmp/ar-p.json -w 'public %{http_code}\n' https://wa.srv1802669.hstgr.cloud/agent-reports/health; head -c 300 /tmp/ar-p.json; echo"
    ;;

  agent-reports-fix-nginx)
    [[ $# -eq 0 ]] || die "agent-reports-fix-nginx takes no arguments"
    src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../agent-reports/deploy" && pwd)"
    scp.exe -i "$KEY" "${SSH_OPTS[@]}" "$src/fix_nginx.py" "$HOST:/opt/a7-wa/agent-reports/deploy/fix_nginx.py"
    scp.exe -i "$KEY" "${SSH_OPTS[@]}" "$src/nginx-snippet.conf" "$HOST:/opt/a7-wa/agent-reports/deploy/nginx-snippet.conf"
    remote "python3 /opt/a7-wa/agent-reports/deploy/fix_nginx.py && nginx -t && systemctl reload nginx"
    remote "curl -sk -H 'Host: wa.srv1802669.hstgr.cloud' -o /tmp/ar-n.json -w 'nginx-host %{http_code}\n' https://127.0.0.1/agent-reports/health; head -c 400 /tmp/ar-n.json; echo"
    ;;

  agent-reports-sync-owner-phones)
    # Bulk-link Owner Data phone UFs → Contacts (call button). Optional flags only.
    dry_run=0
    limit=""
    do_all=0
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --dry-run) dry_run=1 ;;
        --limit)
          [[ $# -ge 2 ]] || die "--limit needs a number"
          [[ "$2" =~ ^[0-9]+$ ]] || die "--limit must be an integer"
          limit="$2"
          shift
          ;;
        --all) do_all=1 ;;
        *) die "agent-reports-sync-owner-phones: unknown arg '$1' (want --dry-run|--limit N|--all)" ;;
      esac
      shift
    done
    args=()
    [[ "$dry_run" -eq 1 ]] && args+=(--dry-run)
    [[ -n "$limit" ]] && args+=(--limit "$limit")
    [[ "$do_all" -eq 1 ]] && args+=(--all)
    if [[ ${#args[@]} -eq 0 ]]; then
      remote "cd /opt/a7-wa/agent-reports/deploy && docker compose exec -T web \
        python scripts/bulk_link_owner_phones.py"
    else
      # shellcheck disable=SC2029
      remote "cd /opt/a7-wa/agent-reports/deploy && docker compose exec -T web \
        python scripts/bulk_link_owner_phones.py $(printf '%q ' "${args[@]}")"
    fi
    ;;

  raise-upload-limit)
    # Official inbox + OpenWA dashboard. Only this one number, only the
    # body-size line, so a 90 MB video is not 413'd at nginx.
    [[ $# -eq 0 ]] || die "raise-upload-limit takes no arguments"
    remote 'set -eu
      for f in /etc/nginx/conf.d/a7-wa.conf /etc/nginx/conf.d/a7-openwa.conf \
               /etc/nginx/sites-enabled/a7-wa.conf /etc/nginx/sites-enabled/a7-openwa.conf; do
        [ -f "$f" ] || continue
        sed -i "s/client_max_body_size [0-9]\+[mMkK];/client_max_body_size 1024m;/" "$f"
        echo "updated $f"
        grep -n client_max_body_size "$f" || true
      done
      nginx -t
      systemctl reload nginx
    '
    ;;

  set-meta-graph-token)
    # Writes META_GRAPH_ACCESS_TOKEN on the Official host from a local file
    # (first line), recreates web/worker/beat so the new env is read, then
    # runs the read-only probe. The token travels on stdin — never on a
    # command line, never printed here. Shape-checked so this cannot become
    # an arbitrary .env edit.
    token_file="${1:-}"
    [[ -f "$token_file" ]] || die "set-meta-graph-token wants a file whose first line is the token"
    token="$(head -n1 "$token_file" | tr -d '\r\n[:space:]')"
    [[ "$token" =~ ^[A-Za-z0-9_.-]{40,600}$ ]] || die "that file's first line does not look like a Meta access token"
    printf '%s\n' "$token" | remote 'set -eu
      IFS= read -r t
      f=/opt/a7-wa/deploy/.env
      [ -f "$f" ] || { echo "missing $f"; exit 1; }
      { grep -v "^META_GRAPH_ACCESS_TOKEN=" "$f" || true; } > "$f.tmp"
      printf "META_GRAPH_ACCESS_TOKEN=%s\n" "$t" >> "$f.tmp"
      chmod --reference="$f" "$f.tmp" 2>/dev/null || true
      mv "$f.tmp" "$f"
      echo token=written
      cd /opt/a7-wa/deploy && docker compose up -d web worker beat 2>&1 | tail -3'
    ;;

  set-alots-ui-cookie)
    # Stores a signed-in alots *panel* session on the Official host, from a
    # local file whose first line is the Cookie header string, as base64 in
    # ALOTS_UI_COOKIE_B64. Travels on stdin, never printed. Recreates
    # web/worker/beat, then proves the session with one tiny upload.
    cookie_file="${1:-}"
    [[ -f "$cookie_file" ]] || die "set-alots-ui-cookie wants a file whose first line is the Cookie header"
    cookie="$(head -n1 "$cookie_file" | tr -d '\r\n')"
    [[ ${#cookie} -ge 20 && ${#cookie} -le 8000 && "$cookie" == *=* ]] || die "that file's first line does not look like a Cookie header"
    [[ "$cookie" =~ ^[[:print:]]+$ ]] || die "refusing unusual characters in the cookie"
    encoded_cookie="$(printf '%s' "$cookie" | base64 -w0)"
    printf '%s\n' "$encoded_cookie" | remote 'set -eu
      IFS= read -r c
      f=/opt/a7-wa/deploy/.env
      [ -f "$f" ] || { echo "missing $f"; exit 1; }
      { grep -v "^ALOTS_UI_COOKIE_B64=" "$f" || true; } > "$f.tmp"
      printf "ALOTS_UI_COOKIE_B64=%s\n" "$c" >> "$f.tmp"
      chmod --reference="$f" "$f.tmp" 2>/dev/null || true
      mv "$f.tmp" "$f"
      echo cookie=written
      cd /opt/a7-wa/deploy && docker compose up -d web worker beat 2>&1 | tail -3'
    ;;


  ensure-crm-lead-secret)
    # Writes one env key on the Official host if it is missing. Hex-only so
    # this cannot become an arbitrary .env edit. The same value must be put
    # in Bitrix a7_lead_wa.config.php — this command never prints it.
    secret="${1:-}"
    [[ "$secret" =~ ^[a-fA-F0-9]{64}$ ]] || die "ensure-crm-lead-secret wants 64 hex chars"
    remote "set -eu
      f=/opt/a7-wa/deploy/.env
      [ -f \"\$f\" ] || { echo 'missing /opt/a7-wa/deploy/.env'; exit 1; }
      if grep -q '^CRM_LEAD_WA_SECRET=.' \"\$f\"; then
        echo already-set
        exit 0
      fi
      if grep -q '^CRM_LEAD_WA_SECRET=' \"\$f\"; then
        sed -i 's/^CRM_LEAD_WA_SECRET=.*/CRM_LEAD_WA_SECRET=$secret/' \"\$f\"
      else
        printf '\\nCRM_LEAD_WA_SECRET=$secret\\n' >> \"\$f\"
      fi
      echo written
    "
    ;;

  submit-leadbot-template)
    [[ $# -eq 0 ]] || die "submit-leadbot-template takes no arguments"
    remote "cd $APP_DIR && docker compose exec -T web python manage.py submit_leadbot_template"
    ;;

  submit-leadai-reminder-template)
    # The Lead AI 30-minute meeting reminder (UTILITY, 3 quick replies) to every
    # active agent +971 WABA. Optional --dry-run lists the WABAs only.
    flag=""
    if [[ $# -eq 1 && "$1" == "--dry-run" ]]; then
      flag="--dry-run"
    elif [[ $# -ne 0 ]]; then
      die "submit-leadai-reminder-template takes no arguments, or --dry-run"
    fi
    remote "cd $APP_DIR && docker compose exec -T web python manage.py submit_leadai_reminder_template $flag"
    ;;

  leadai-switch)
    # The Lead AI assistant's switch: on, off (an emergency stop) or status.
    action="${1:-}"
    [[ $# -eq 1 && "$action" =~ ^(on|off|status)$ ]] || die "leadai-switch takes on, off or status"
    remote "cd $APP_DIR && docker compose exec -T web python manage.py leadai_switch $action"
    ;;

  leadai-test-numbers)
    # The customer numbers the assistant answers while it is switched off.
    # No argument clears the list; each argument must be 8-15 digits.
    for n in "$@"; do
      [[ "$n" =~ ^[0-9]{8,15}$ ]] || die "'$n' is not a phone number with country code (digits only)"
    done
    remote "cd $APP_DIR && docker compose exec -T web python manage.py leadai_switch test-numbers $*"
    ;;

  leadai-alert-ids)
    # Bitrix user ids that also get the assistant's booking, broker, handover
    # and unanswered-message alerts. No argument clears the list.
    for n in "$@"; do
      [[ "$n" =~ ^[0-9]{1,10}$ ]] || die "'$n' is not a Bitrix user id (digits only)"
    done
    remote "cd $APP_DIR && docker compose exec -T web python manage.py leadai_switch alert-ids $*"
    ;;

  set-leadai-office)
    # The office's Google Maps link and pin for Lead AI (confirmations, reminders,
    # the location pin), checked by the settings view's own validators and kept
    # in the settings history. Only a maps.app.goo.gl short link and plain
    # decimal coordinates pass, so nothing here can break the quoting below.
    [[ $# -eq 3 ]] || die "set-leadai-office takes URL LAT LNG"
    [[ "$1" =~ ^https://maps\.app\.goo\.gl/[A-Za-z0-9]+$ ]] || die "the link must be https://maps.app.goo.gl/<code>"
    [[ "$2" =~ ^-?[0-9]{1,2}\.[0-9]{1,8}$ ]] || die "'$2' is not a latitude"
    [[ "$3" =~ ^-?[0-9]{1,3}\.[0-9]{1,8}$ ]] || die "'$3' is not a longitude"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/set-leadai-office.py"
    [[ -f "$script" ]] || die "missing ops/catalog/set-leadai-office.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && base64 -d | docker compose exec -T \
      -e LEADAI_OFFICE_MAPS_URL='$1' -e LEADAI_OFFICE_LAT='$2' -e LEADAI_OFFICE_LNG='$3' web python manage.py shell"
    ;;

  ""|-h|--help|help) usage ;;
  *) die "unknown command '$cmd' — try: ops/wa.sh help" ;;
esac
