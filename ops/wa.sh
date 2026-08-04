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
#   ops/wa.sh build qr app                rebuild an image
#   ops/wa.sh restart qr app              restart services
#   ops/wa.sh up qr app                   recreate a service (after a build)
#   ops/wa.sh unlock                      clear stale Chromium profile locks
#   ops/wa.sh django-check                the two checks CLAUDE.md requires

set -euo pipefail

HOST="root@187.127.123.235"
KEY="C:/Users/Matloob/.ssh/hostinger_codex"
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
SSH_OPTS=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$KNOWN_HOSTS"
)

# The only two places anything is allowed to happen.
QR_DIR="/opt/a7-wa/wa-qr"
APP_DIR="/opt/a7-wa/deploy"

die() { echo "wa.sh: $*" >&2; exit 2; }

remote() { ssh.exe -i "$KEY" "${SSH_OPTS[@]}" "$HOST" "$@"; }

# The compose directory for a stack name, refusing anything else outright.
stack_dir() {
  case "${1:-}" in
    qr)  echo "$QR_DIR" ;;
    app) echo "$APP_DIR" ;;
    *)   die "unknown stack '${1:-}' — it is 'qr' or 'app'" ;;
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

# Somewhere under /opt/a7-wa, and provably so — no `..`, no absolute escape, no
# characters a shell would read as anything other than a path.
check_remote_path() {
  local p="${1:-}"
  [[ "$p" == /opt/a7-wa/* ]] || die "refusing a path outside /opt/a7-wa: '$p'"
  [[ "$p" != *..* ]]         || die "refusing a path containing '..': '$p'"
  [[ "$p" =~ ^[A-Za-z0-9._/@-]+$ ]] || die "refusing unusual characters in: '$p'"
}

usage() { sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

cmd="${1:-}"
shift || true

case "$cmd" in

  ps)
    remote "cd $QR_DIR && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'; \
            echo '---'; \
            cd $APP_DIR && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Status}}'"
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

  build)
    dir=$(stack_dir "${1:-}"); check_service "${2:-}"
    remote "cd $dir && docker compose build '$2' 2>&1 | tail -3"
    ;;

  up)
    dir=$(stack_dir "${1:-}"); check_service "${2:-}"
    # `up -d` and not `restart`, because a rebuilt image only reaches a
    # container that is recreated. `restart` starts the old one again.
    remote "cd $dir && docker compose up -d '$2' 2>&1 | tail -3"
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

  django-check)
    # The two CLAUDE.md insists on after any migration work. Fixed, not a
    # passthrough — `manage.py <anything>` would be arbitrary execution again.
    remote "cd $APP_DIR && docker compose exec -T web python manage.py makemigrations --check --dry-run; \
            echo '---'; \
            cd $APP_DIR && docker compose exec -T web python manage.py showmigrations"
    ;;

  ""|-h|--help|help) usage ;;
  *) die "unknown command '$cmd' — try: ops/wa.sh help" ;;
esac
