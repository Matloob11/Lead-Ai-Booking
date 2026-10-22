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
#   ops/wa.sh ps                          app stack container states
#   ops/wa.sh logs app web [200]          container logs
#   ops/wa.sh sql app "SELECT 1"          read-only query (writes are refused)
#   ops/wa.sh sum /opt/a7-wa/panel/x.js   checksum of a deployed file
#   ops/wa.sh get /app/assets/x.js        fetch from the public site
#   ops/wa.sh push local remote           copy one file to the server
#   ops/wa.sh sync src /opt/a7-wa/panel   copy a directory to the server
#   ops/wa.sh panel [stale…]              publish bitrix/public to /opt/a7-wa/panel
#   ops/wa.sh agent-reports-deploy        publish agent-reports stack + nginx location
#   ops/wa.sh agent-reports-check         compose + public /agent-reports/ health
#   ops/wa.sh agent-reports-fix-nginx    move/refresh /agent-reports/ into :443 server
#   ops/wa.sh agent-reports-sync-owner-phones [--dry-run] [--limit N] [--all]
#   ops/wa.sh build app                   rebuild every app image (no service arg)
#   ops/wa.sh restart app [service]       restart services
#   ops/wa.sh up app                      recreate web/worker/worker-leadai/beat
#   ops/wa.sh migrate                     apply pending Django migrations (app stack)
#   ops/wa.sh migrate-new-image           the same, from the image just built, before `up`
#   ops/wa.sh leadai-tests                Lead AI tests in the new image, throwaway test DB, nothing leaves
#   ops/wa.sh probe-leadai-turn           3 real assistant turns on live data + key, rolled back, nothing sent
#   ops/wa.sh probe-leadai-funnel [--weeks N]  weekly Lead AI funnel, WhatsApp side (T73): counts only, read-only
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
#   ops/wa.sh set-meta-graph-token FILE    write META_GRAPH_ACCESS_TOKEN; up -d all app services; then probe-media-template-path
#   ops/wa.sh set-alots-ui-cookie FILE     store alots Cookie; up -d all app services; then probe-media-template-path
#   ops/wa.sh credit-status               read-only gateway credit poll + panel flags (never the balance)
#   ops/wa.sh submit-aldardso-missing     submit aldardso to the eight 971 numbers that lack it
#   ops/wa.sh credit-release              reclaim parked credit rows and start their campaigns (writer)
#   ops/wa.sh probe-backend-md5           md5 of every source file in the running web image
#   ops/wa.sh raise-upload-limit            Official nginx body size → 1024m
#   ops/wa.sh ensure-crm-lead-secret HEX    set CRM_LEAD_WA_SECRET if empty (64 hex)
#   ops/wa.sh submit-leadbot-template       submit a7_lead_enquiry_confirm to agent 971 WABAs
#   ops/wa.sh submit-leadai-reminder-template [--dry-run]  Lead AI meeting reminder to every active assigned WABA
#   ops/wa.sh leadai-switch on|off|status   the Lead AI assistant's switch
#   ops/wa.sh leadai-test-numbers [digits…] numbers the assistant answers while it is off
#   ops/wa.sh leadai-alert-ids [ids…]       Bitrix users who also get booking/broker/handover alerts
#   ops/wa.sh set-leadai-office URL LAT LNG  the office's Google Maps short link and pin for Lead AI
#   ops/wa.sh set-leadai-office-address "TEXT"  the office address text Lead AI sends
#   ops/wa.sh leadai-media-import DIR [--dry-run]  shop videos/photos from DIR (under /app/media/leadai_import) into Lead AI
#   ops/wa.sh leadai-optout-import [--dry-run]  past Unsubscribe/Stop/wrong-number messages into the opt-out registry
#   ops/wa.sh submit-shops-templates [--dry-run]  shops Template B + Template A (video) to the 8 sending WABAs that lack them
#   ops/wa.sh submit-portal-enquiry-template [--dry-run] [--category UTILITY|MARKETING]  C68 portal_enquiry_reply to the 8 sending WABAs
#   ops/wa.sh crm-mirror-backfill [--since 2026-10-14T07:40:00Z] [--leadai] [--dry-run] [--limit N] [--every S]  re-queue the CRM timeline mirror (counts only)
#   ops/wa.sh load                        host load, RAM, disk, top containers
#   ops/wa.sh leadai-greet-settings on|off [number] [bitrix id] [template] [hours]  the new-lead greet's settings
#   ops/wa.sh leadai-health                 Lead AI health: sweep, queue, last hour, who waits, inventory, keys

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
APP_DIR="/opt/a7-wa/deploy"
# OpenWA is a separate trial stack with its own compose file and its own root.
# Added deliberately rather than by loosening the check to /opt: this is a second
# named directory, not a wildcard, and everything below still refuses anything
# that is not provably inside one of them.

die() { echo "wa.sh: $*" >&2; exit 2; }

remote() { ssh.exe -i "$KEY" "${SSH_OPTS[@]}" "$HOST" "$@"; }

# The compose directory for a stack name, refusing anything else outright.
stack_dir() {
  case "${1:-}" in
    app) echo "$APP_DIR" ;;
    *)   die "unknown stack '${1:-}' — it is 'app'" ;;
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
  [[ "$p" == /opt/a7-wa/* ]] ||
    die "refusing a path outside /opt/a7-wa: '$p'"
  [[ "$p" =~ ^[A-Za-z0-9._/@-]+$ ]] || die "refusing unusual characters in: '$p'"
}

usage() { sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

cmd="${1:-}"
shift || true

case "$cmd" in

  ps)
    remote "cd $APP_DIR && docker compose ps --format '{{.Service}}	{{.State}}	{{.Status}}'"
    ;;

  logs)
    dir=$(stack_dir "${1:-}"); check_service "${2:-}"; lines="${3:-120}"; check_count "$lines"
    remote "cd $dir && docker compose logs '$2' --tail $lines --no-log-prefix"
    ;;

  sql)
    dir=$(stack_dir "${1:-}")
    query="${2:-}"
    [[ -n "$query" ]] || die "sql needs a query"

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
    # Always recreate every app service so worker-leadai is never left behind.
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

  add-dubai01-05-numbers)
    # The 38 sheet numbers Dubai01WBX–Dubai05WBX were missing from the panel.
    [[ $# -eq 0 ]] || die "add-dubai01-05-numbers takes no arguments"
    add_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/add-dubai01-05-numbers.py"
    [[ -f "$add_script" ]] || die "missing ops/catalog/add-dubai01-05-numbers.py"
    encoded=$(base64 -w0 < "$add_script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  set-number-quality)
    # Sheet All Active Accounts: High -> HIGH, Low -> YELLOW.
    [[ $# -eq 0 ]] || die "set-number-quality takes no arguments"
    quality_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/set-number-quality.py"
    [[ -f "$quality_script" ]] || die "missing ops/catalog/set-number-quality.py"
    encoded=$(base64 -w0 < "$quality_script")
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
    remote "cd $APP_DIR && docker compose exec -T $service python manage.py leadai_eval ${args[*]:-} 2>&1 | tail -600"
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

  leadai-answer-late)
    # One-off (2026-10-19): answer the replies to campaigns 549-553 that the Lead AI
    # dropped as too old in the reply burst after the send, through the normal engine
    # turn (ops/catalog/leadai-answer-late.py). "list" prints what it would answer and
    # sends nothing; "send" answers them. An optional limit caps how many one run takes.
    mode="${1:-list}"; limit="${2:-100}"
    [[ "$mode" == list || "$mode" == send ]] || die "leadai-answer-late takes list or send, then an optional limit"
    [[ "$limit" =~ ^[0-9]{1,3}$ ]] || die "the limit must be a number up to 999"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/leadai-answer-late.py"
    [[ -f "$script" ]] || die "missing ops/catalog/leadai-answer-late.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T -e LATE_MODE=$mode -e LATE_LIMIT=$limit web python manage.py shell"
    ;;

  probe-leadai-funnel)
    # Read-only (board T73, the WhatsApp half of the weekly funnel): per ISO week (Asia/Dubai), per
    # playbook and in total, Lead AI campaign messages sent / delivered / read / failed, and the chats
    # that replied, booked a visit, were handed over or opted out, with the median minutes from their
    # first reply to our first answer. Counts only; one READ ONLY transaction, rolled back. Optional
    # --weeks N, 1-26 (default 8).
    weeks=8
    if [[ $# -eq 2 && "$1" == "--weeks" ]]; then
      [[ "$2" =~ ^([1-9]|1[0-9]|2[0-6])$ ]] || die "--weeks takes 1 to 26"
      weeks="$2"
    elif [[ $# -ne 0 ]]; then
      die "probe-leadai-funnel takes no arguments, or --weeks N (1-26)"
    fi
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-leadai-funnel.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-leadai-funnel.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T -e LEADAI_FUNNEL_WEEKS='$weeks' web python manage.py shell"
    ;;

  credit-status)
    # Read-only (C29): poll the wallet and show out/low/waiting. Never parks,
    # releases or starts a campaign. Never prints the balance figure.
    [[ $# -eq 0 ]] || die "credit-status takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/credit-status.py"
    [[ -f "$script" ]] || die "missing ops/catalog/credit-status.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  submit-aldardso-missing)
    # Submit the existing aldardso template to 971581058719–726 only.
    # A WABA that already has the name is left as it is. No campaign is sent.
    [[ $# -eq 0 ]] || die "submit-aldardso-missing takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/submit-aldardso-missing.py"
    [[ -f "$script" ]] || die "missing ops/catalog/submit-aldardso-missing.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  check-aldardso-eight)
    # Read Meta's status for aldardso on 971581058719–726. No send.
    [[ $# -eq 0 ]] || die "check-aldardso-eight takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/check-aldardso-eight.py"
    [[ -f "$script" ]] || die "missing ops/catalog/check-aldardso-eight.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  credit-release)
    # Writer (C29): reclaim parked credit rows and start their campaigns.
    # Deliberate — the old probe-c16-credit did this while named like a probe.
    [[ $# -eq 0 ]] || die "credit-release takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/credit-release.py"
    [[ -f "$script" ]] || die "missing ops/catalog/credit-release.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  probe-c16-credit)
    die "probe-c16-credit was a writer named as a probe; use credit-status or credit-release"
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
    # (first line), then ``docker compose up -d`` with no service list so
    # worker-leadai gets the new env too. After this, run
    # ``ops/wa.sh probe-media-template-path``. The token travels on stdin —
    # never on a command line, never printed here.
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
      cd /opt/a7-wa/deploy && docker compose up -d 2>&1 | tail -5'
    ;;

  set-alots-ui-cookie)
    # Stores a signed-in alots *panel* session on the Official host, from a
    # local file whose first line is the Cookie header string, as base64 in
    # ALOTS_UI_COOKIE_B64. Travels on stdin, never printed. Then
    # ``docker compose up -d`` with no service list so worker-leadai gets the
    # new env too. After this, run ``ops/wa.sh probe-media-template-path``.
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
      cd /opt/a7-wa/deploy && docker compose up -d 2>&1 | tail -5'
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

  leadai-move-to-inbox)
    # Desk "Move to inbox" for Lead AI chat ids (pk of leadai_leadaichat). Digits only.
    [[ $# -ge 1 ]] || die "leadai-move-to-inbox takes one or more Lead AI chat ids"
    ids=()
    for n in "$@"; do
      [[ "$n" =~ ^[0-9]{1,10}$ ]] || die "'$n' is not a Lead AI chat id"
      ids+=("$n")
    done
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/leadai-move-to-inbox.py"
    [[ -f "$script" ]] || die "missing ops/catalog/leadai-move-to-inbox.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && base64 -d | docker compose exec -T \
      -e LEADAI_MOVE_INBOX_IDS='${ids[*]}' web python manage.py shell"
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

  set-leadai-office-address)
    # The office address text Lead AI sends in confirmations and reminders, set the
    # way the AI settings dialog sets it and kept in the settings history. Only
    # letters, digits, spaces and , . / # ( ) - pass, so nothing here can break
    # the quoting below.
    [[ $# -eq 1 ]] || die "set-leadai-office-address takes one quoted address"
    address_ok='^[A-Za-z0-9 ,./#()-]{5,200}$'
    [[ "$1" =~ $address_ok ]] || die "the address may hold letters, digits, spaces and , . / # ( ) - (5-200 characters)"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/set-leadai-office-address.py"
    [[ -f "$script" ]] || die "missing ops/catalog/set-leadai-office-address.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && base64 -d | docker compose exec -T \
      -e LEADAI_OFFICE_ADDRESS='$1' web python manage.py shell"
    ;;

  leadai-media-import)
    # The build pack's shop media into the Lead AI media library (board T30): one folder
    # per type ("Type 1 ...", the typo "Tpye 2 ...", "Type 3 ..."), the office photo
    # (a file whose name starts with "office") at the top, files in name order, each
    # checked by its bytes. Run in the web container on a folder of the media volume:
    # first `ops/wa.sh sync <local folder named leadai_import> /opt/a7-wa/media`, then
    # this with /app/media/leadai_import (its own name may hold no space; the folders
    # inside it may). --dry-run checks and reports, and stores nothing. Running it twice
    # adds nothing twice.
    dir="${1:-}"
    [[ "$dir" == /app/media/leadai_import || "$dir" == /app/media/leadai_import/* ]] ||
      die "leadai-media-import takes a folder under /app/media/leadai_import"
    [[ "$dir" != *..* ]] || die "refusing '..' in: '$dir'"
    [[ "$dir" =~ ^[A-Za-z0-9._/-]+$ ]] || die "refusing unusual characters in: '$dir'"
    flag=""
    if [[ $# -eq 2 && "$2" == "--dry-run" ]]; then
      flag="--dry-run"
    elif [[ $# -ne 1 ]]; then
      die "leadai-media-import takes DIR, or DIR --dry-run"
    fi
    remote "cd $APP_DIR && docker compose exec -T web python manage.py leadai_media_import '$dir' $flag"
    ;;

  leadai-optout-import)
    # Back-fill the WhatsApp opt-out registry (board T60, Q8) from what customers already
    # said: an Unsubscribe / Stop / Stop messages / Stop promotions tap, a STOP or a wrong
    # number typed, and the Lead AI chats stopped for those. --dry-run counts, shows ten
    # and stores nothing. A phone already blocked keeps its first reason.
    flag=""
    if [[ $# -eq 1 && "$1" == "--dry-run" ]]; then
      flag="--dry-run"
    elif [[ $# -ne 0 ]]; then
      die "leadai-optout-import takes no arguments, or --dry-run"
    fi
    remote "cd $APP_DIR && docker compose exec -T web python manage.py leadai_optout_import $flag"
    ;;

  submit-shops-templates)
    # The International City shops templates (board T61) to the eight sending numbers'
    # WABAs (board D4): intl_city_shops_followup (Template B, which the automatic
    # follow-ups send) and intl_city_shops_reconnect (Template A, whose video header is
    # reviewed against the Type 1 video of the Lead AI media library). A WABA that has
    # one already, in any status, keeps it untouched. --dry-run says what would go and
    # uploads and submits nothing.
    flag=""
    if [[ $# -eq 1 && "$1" == "--dry-run" ]]; then
      flag="--dry-run"
    elif [[ $# -ne 0 ]]; then
      die "submit-shops-templates takes no arguments, or --dry-run"
    fi
    remote "cd $APP_DIR && docker compose exec -T web python manage.py submit_shops_templates $flag"
    ;;

  submit-portal-enquiry-template)
    # Board C68: portal_enquiry_reply (UTILITY by default; --category MARKETING if Meta
    # refuses) to the eight sending numbers' WABAs (board D4). Idempotent. --dry-run lists
    # WABAs and submits nothing. Optional: --category UTILITY|MARKETING.
    flag=""
    category=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --dry-run) flag="--dry-run"; shift ;;
        --category)
          [[ "${2:-}" =~ ^(UTILITY|MARKETING)$ ]] || die "--category takes UTILITY or MARKETING"
          category="--category $2"; shift 2 ;;
        *) die "submit-portal-enquiry-template takes --dry-run and/or --category UTILITY|MARKETING" ;;
      esac
    done
    remote "cd $APP_DIR && docker compose exec -T web python manage.py submit_portal_enquiry_template $flag $category"
    ;;

  submit-reconnect-again-template)
    # Reconnect again (apps/leadai/reconnect.py; Matloob 2026-10-22): intl_city_property_reconnect_again (MARKETING,
    # {{1}} the first name, the mixed template's three quick replies) to the eight sending numbers' WABAs. A WABA that
    # has it already, in any status, keeps it. --dry-run says what would go and submits nothing.
    flag=""
    if [[ $# -eq 1 && "$1" == "--dry-run" ]]; then
      flag="--dry-run"
    elif [[ $# -ne 0 ]]; then
      die "submit-reconnect-again-template takes no arguments, or --dry-run"
    fi
    remote "cd $APP_DIR && docker compose exec -T web python manage.py submit_reconnect_again_template $flag"
    ;;

  leadai-reconnect-again)
    # Reconnect again: the audience of these Lead AI campaigns (who gets the second template in their chat, who gets a
    # fresh send, who is left out and why), and with --send the sends themselves, inside Template B's hours:
    #   ops/wa.sh leadai-reconnect-again 549,550,551,552,553
    #   ops/wa.sh leadai-reconnect-again 549,550,551,552,553 --show 20
    #   ops/wa.sh leadai-reconnect-again 549,550,551,552,553 --send [--limit N] [--agent <bitrix id>] [--quiet-hours N] [--any-hour]
    ids="${1:-}"
    [[ "$ids" =~ ^[0-9]{1,7}(,[0-9]{1,7}){0,30}$ ]] || die "campaign ids: digits separated by commas, e.g. 549,550"
    shift
    args=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --send|--any-hour) args="$args $1"; shift ;;
        --limit|--quiet-hours|--show) [[ "${2:-}" =~ ^[0-9]{1,5}$ ]] || die "$1 takes a number"; args="$args $1 $2"; shift 2 ;;
        --agent) [[ "${2:-}" =~ ^[0-9]{1,8}$ ]] || die "--agent takes a Bitrix user id"; args="$args --agent $2"; shift 2 ;;
        *) die "leadai-reconnect-again: unknown option $1" ;;
      esac
    done
    remote "cd $APP_DIR && docker compose exec -T web python manage.py leadai_reconnect_again --campaigns $ids$args"
    ;;

  submit-ic-templates)
    # The International City mixed template (board Q34): intl_city_property_reconnect to the
    # eight sending numbers' WABAs (board D4). A WABA that has it already, in any status, keeps it
    # untouched. --dry-run says what would go and submits nothing. Runs in beat, whose /app is the
    # build context, because the command is new there before the 2e image is built.
    flag=""
    if [[ $# -eq 1 && "$1" == "--dry-run" ]]; then
      flag="--dry-run"
    elif [[ $# -ne 0 ]]; then
      die "submit-ic-templates takes no arguments, or --dry-run"
    fi
    remote "cd $APP_DIR && docker compose exec -T beat python manage.py submit_ic_templates $flag"
    ;;

  submit-leadai-reminder-v2-template)
    # Board T45: the meeting reminder v2 (v1's three quick replies plus [Office Location]) to
    # the eight sending numbers' WABAs (board D4). Idempotent. --dry-run lists the WABAs. Runs in beat,
    # whose /app is the build context, because the command is new there before the 2e image.
    flag=""
    if [[ $# -eq 1 && "$1" == "--dry-run" ]]; then
      flag="--dry-run"
    elif [[ $# -ne 0 ]]; then
      die "submit-leadai-reminder-v2-template takes no arguments, or --dry-run"
    fi
    remote "cd $APP_DIR && docker compose exec -T beat python manage.py submit_leadai_reminder_v2_template $flag"
    ;;

  set-leadai-shops-clusters)
    # Board Q42: the shop clusters Lead AI names, as the AI settings dialog sets them (validated by
    # shops.validate, recorded in the settings history). One argument: the comma-separated list.
    [[ $# -eq 1 ]] || die "set-leadai-shops-clusters takes one argument: \"France, England, ...\""
    clusters_ok='^[A-Za-z ,]{3,200}$'
    [[ "$1" =~ $clusters_ok ]] || die "refusing: letters, spaces and commas only"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/set-leadai-shops-clusters.py"
    [[ -f "$script" ]] || die "missing ops/catalog/set-leadai-shops-clusters.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && base64 -d | docker compose exec -T -e LEADAI_SHOPS_CLUSTERS='$1' web python manage.py shell"
    ;;

  crm-mirror-backfill)
    # Board T57 and the Bitrix REST throttle: queue the CRM timeline mirror again for
    # messages that never reached their record. --since UTC picks every message from
    # then on (each task posts only what its records miss); --leadai picks every
    # message of every Lead AI chat not on the chat's own lead yet. At least one of
    # the two. Campaign templates, panel copies, reactions, system notes, failed sends
    # and the last 5 minutes are never picked. Tasks go one every --every seconds
    # (1-60, default 8), at most --limit (1-20000, default 2000) and never more than
    # 45 minutes ahead; run it again for the rest once those have run, from the
    # --since it prints. Refused while a campaign is sending. Nothing is posted twice
    # (Mirror, and a look at the timeline first). --dry-run counts and queues nothing.
    # Prints counts only. Every value is checked here, whole, before anything reaches
    # the server.
    args=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --since)
          [[ "${2:-}" =~ ^20[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$ ]] ||
            die "--since takes a UTC time like 2026-10-14T07:40:00Z"
          args+=(--since "$2"); shift 2 ;;
        --leadai|--dry-run) args+=("$1"); shift ;;
        --limit)
          [[ "${2:-}" =~ ^([1-9][0-9]{0,3}|1[0-9]{4}|20000)$ ]] || die "--limit takes 1 to 20000"
          args+=(--limit "$2"); shift 2 ;;
        --every)
          [[ "${2:-}" =~ ^([1-9]|[1-5][0-9]|60)$ ]] || die "--every takes 1 to 60 (seconds)"
          args+=(--every "$2"); shift 2 ;;
        *) die "crm-mirror-backfill takes --since TIME, --leadai, --dry-run, --limit N and --every S" ;;
      esac
    done
    [[ " ${args[*]:-} " == *" --since "* || " ${args[*]:-} " == *" --leadai "* ]] ||
      die "crm-mirror-backfill needs --since TIME, --leadai, or both"
    remote "cd $APP_DIR && docker compose exec -T web python manage.py crmlink_backfill_mirrors ${args[*]}"
    ;;

  hooks-worker)
    # A second container that only applies webhook rows (replies, delivered, read).
    # Does not recreate the campaign worker.
    [[ $# -eq 0 ]] || die "hooks-worker takes no arguments"
    remote "set -eu
      cd $APP_DIR
      test -f $APP_DIR/a7_drain_hooks.py
      if docker ps -a --format '{{.Names}}' | grep -qx 'a7wa-worker-hooks'; then
        echo 'a7wa-worker-hooks already exists'
        docker ps -a --filter name=a7wa-worker-hooks --format '{{.Names}} {{.Status}}'
        exit 0
      fi
      docker compose run -d -T --name a7wa-worker-hooks --no-deps \
        -v $APP_DIR/a7_drain_hooks.py:/tmp/a7_drain_hooks.py:ro \
        worker python /tmp/a7_drain_hooks.py
      docker ps --filter name=a7wa-worker-hooks --format '{{.Names}} {{.Status}}'
    "
    ;;

  worker-pool-grow)
    # Add 1 or 2 processes to the running inbox worker. Does not restart it,
    # so a campaign already sending keeps its place. The next container start
    # goes back to the compose concurrency.
    n="${1:-}"
    [[ $# -eq 1 && "$n" =~ ^[12]$ ]] || die "worker-pool-grow takes 1 or 2"
    remote "cd $APP_DIR && docker compose exec -T worker celery -A a7wa control pool_grow $n"
    ;;

  ""|-h|--help|help) usage ;;
  probe-leadai-desk)
    # Read-only: as the real responsibles of the chats on a handover desk (round 23), does the desk show exactly their
    # chats, trimmed, and refuse the rest (ops/catalog/probe-leadai-desk.py)? Phones masked; nothing written.
    [[ $# -eq 0 ]] || die "probe-leadai-desk takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/probe-leadai-desk.py"
    [[ -f "$script" ]] || die "missing ops/catalog/probe-leadai-desk.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  leadai-greet-settings)
    # The new-lead greet's settings (apps/leadai/assistant/newlead.py, round 22), set as the
    # Django admin form would and checked as the greet checks them (ops/catalog/leadai-greet-settings.py):
    #   ops/wa.sh leadai-greet-settings off
    #   ops/wa.sh leadai-greet-settings on <number digits> <bitrix user id> <template name> [hours]
    mode="${1:-}"
    [[ "$mode" == "on" || "$mode" == "off" ]] || die "leadai-greet-settings takes on or off first"
    number="${2:-}"; agent="${3:-}"; template="${4:-}"; hours="${5:-48}"
    if [[ "$mode" == "on" ]]; then
      [[ "$number" =~ ^[0-9]{9,15}$ ]] || die "the number is its digits: '$number'"
      [[ "$agent" =~ ^[0-9]{1,8}$ ]] || die "a Bitrix user id is a number: '$agent'"
      [[ "$template" =~ ^[a-z0-9_]{1,80}$ ]] || die "a template name is lower-case letters, digits and underscores: '$template'"
      [[ "$hours" =~ ^[0-9]{1,3}$ ]] || die "hours is a number: '$hours'"
    fi
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/leadai-greet-settings.py"
    [[ -f "$script" ]] || die "missing ops/catalog/leadai-greet-settings.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && base64 -d | docker compose exec -T       -e GREET_ON=$mode -e GREET_NUMBER=$number -e GREET_AGENT=$agent -e GREET_TEMPLATE=$template -e GREET_HOURS=$hours       web python manage.py shell"
    ;;

  leadai-grant-access)
    # Give Lead AI access (Agent.can_lead_ai) to agents by Bitrix id, as "Agents & access"
    # would (ops/catalog/leadai-grant-access.py). Ids only; the script skips an agent
    # without Official API access and says so.
    [[ $# -ge 1 ]] || die "leadai-grant-access takes one or more Bitrix ids"
    ids=""
    for id in "$@"; do
      [[ "$id" =~ ^[0-9]{1,8}$ ]] || die "a Bitrix id is a number: '$id'"
      ids="${ids:+$ids,}$id"
    done
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/leadai-grant-access.py"
    [[ -f "$script" ]] || die "missing ops/catalog/leadai-grant-access.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && \
      base64 -d | docker compose exec -T -e GRANT_IDS=$ids web python manage.py shell"
    ;;

  leadai-health)
    # The Lead AI's health in one screen (apps/leadai/management/commands/leadai_health.py):
    # the switch, the sweep's age (worker-leadai alive?), the leadai queue's depth, the last
    # hour's turns, who waits for a person, the inventory's age, the keys, the last digest.
    # Read only; exit 1 when something is red.
    [[ $# -eq 0 ]] || die "leadai-health takes no arguments"
    remote "cd $APP_DIR && docker compose exec -T web python manage.py leadai_health"
    ;;

  leadai-sync-inventory)
    # The Lead AI inventory refreshed now (apps/leadai/assistant/inventory.py: Property
    # Finder's live listings and the clean Availability cards), with the counts and a few
    # units printed (ops/catalog/leadai-sync-inventory.py). The beat job does the same every
    # half hour; this proves it after a deploy.
    [[ $# -eq 0 ]] || die "leadai-sync-inventory takes no arguments"
    script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/catalog/leadai-sync-inventory.py"
    [[ -f "$script" ]] || die "missing ops/catalog/leadai-sync-inventory.py"
    encoded=$(base64 -w0 < "$script")
    printf '%s' "$encoded" | remote "cd $APP_DIR && base64 -d | docker compose exec -T web python manage.py shell"
    ;;

  set-pf-api-keys)
    # Writes LEADAI_PF_API_KEY and LEADAI_PF_API_SECRET on the Official host (the Lead AI
    # inventory, apps/leadai/assistant/inventory.py) from a local, gitignored env file that
    # holds PF_API_KEY=... and PF_API_SECRET=... lines. They travel on stdin, never on a
    # command line, never printed. No ``up`` here: the deploy that ships the code does it
    # (env_file is read when a container is created).
    keys_file="${1:-}"
    [[ -f "$keys_file" ]] || die "set-pf-api-keys wants the local propertyfinder.env file"
    pf_key="$(grep -E '^PF_API_KEY=' "$keys_file" | head -n1 | cut -d= -f2- | tr -d '\r\n[:space:]')"
    pf_secret="$(grep -E '^PF_API_SECRET=' "$keys_file" | head -n1 | cut -d= -f2- | tr -d '\r\n[:space:]')"
    [[ "$pf_key" =~ ^[A-Za-z0-9_.-]{20,200}$ ]] || die "that file has no PF_API_KEY that looks like one"
    [[ "$pf_secret" =~ ^[A-Za-z0-9_.-]{20,200}$ ]] || die "that file has no PF_API_SECRET that looks like one"
    printf '%s\n%s\n' "$pf_key" "$pf_secret" | remote 'set -eu
      IFS= read -r k; IFS= read -r s
      f=/opt/a7-wa/deploy/.env
      [ -f "$f" ] || { echo "missing $f"; exit 1; }
      { grep -v -e "^LEADAI_PF_API_KEY=" -e "^LEADAI_PF_API_SECRET=" "$f" || true; } > "$f.tmp"
      printf "LEADAI_PF_API_KEY=%s\nLEADAI_PF_API_SECRET=%s\n" "$k" "$s" >> "$f.tmp"
      chmod --reference="$f" "$f.tmp" 2>/dev/null || true
      mv "$f.tmp" "$f"
      echo pf-keys=written'
    ;;

  *) die "unknown command '$cmd' — try: ops/wa.sh help" ;;
esac
