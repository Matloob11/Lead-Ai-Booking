#!/usr/bin/env bash
#
# The Bitrix (AWS Lightsail) counterpart of ops/wa.sh — same philosophy:
# a small fixed vocabulary instead of raw ssh on the allowlist. Everything
# here is READ-ONLY: it exists to audit the 2026-10 snapshot migration
# (old box 13.203.81.218 is retired and must stay off; the new box behind
# crm.a7grouprealestatedxb.com is this HOST). Write/deploy verbs get added
# deliberately, one at a time, once the audit says what is missing.
#
# Usage:
#   ops/bitrix.sh state            services, ports, htsecure, cert, a7 timers, cron
#   ops/bitrix.sh a7               mtimes of every deployed a7_* file (+ init.php)
#   ops/bitrix.sh counts           lead/deal row counts and last-modify stamps
#   ops/bitrix.sh sql "SELECT 1"   read-only query (session forced READ ONLY)
#   ops/bitrix.sh md5 /path        checksum of a deployed file (www/nginx only)
#   ops/bitrix.sh http /path       local curl with the CRM Host header
#   ops/bitrix.sh put local remote copy one file under /home/bitrix/www or /etc/nginx
#   ops/bitrix.sh run a7_foo.php   sudo -u bitrix php of that include file

set -euo pipefail

HOST="${BITRIX_SSH_HOST:-ec2-user@3.108.146.169}"
KEY="${BITRIX_SSH_KEY:-${USERPROFILE//\\//}/.ssh/a7_lightsail}"

KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/known_hosts_bitrix"
SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=20
  -o ServerAliveInterval=10
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$KNOWN_HOSTS"
)

die() { echo "bitrix.sh: $*" >&2; exit 2; }
[[ -f "$KEY" ]] || die "no SSH key at $KEY (set BITRIX_SSH_KEY)"

remote() { ssh.exe -i "$KEY" "${SSH_OPTS[@]}" "$HOST" "$@"; }

# Same rule as wa.sh: a path is a path, provably inside the two roots we audit.
check_remote_path() {
  local p="${1:-}"
  [[ "$p" != *..* ]] || die "refusing a path containing '..': '$p'"
  [[ "$p" == /home/bitrix/www/* || "$p" == /etc/nginx/* ]] ||
    die "refusing a path outside /home/bitrix/www and /etc/nginx: '$p'"
  [[ "$p" =~ ^[A-Za-z0-9._/@-]+$ ]] || die "refusing unusual characters in: '$p'"
}

cmd="${1:-}"
shift || true

case "$cmd" in

  state)
    [[ $# -eq 0 ]] || die "state takes no arguments"
    remote "set -u
      SUDO=''; sudo -n true 2>/dev/null && SUDO='sudo -n'
      echo \"== host ==\"; hostname; uptime; df -hP / | tail -1; echo \"sudo=\${SUDO:-no}\"
      echo '== services =='
      for s in nginx httpd mysqld mariadb crond; do printf '%s=' \"\$s\"; systemctl is-active \"\$s\" 2>/dev/null || true; done
      echo '== listeners =='
      { ss -ltn 2>/dev/null || \$SUDO ss -ltn; } | awk 'NR>1{print \$4}' | grep -E ':(80|443)\$' | sort -u || echo 'no 80/443 listener'
      echo '== htsecure =='
      \$SUDO ls -la /home/bitrix/www/.htsecure /home/bitrix/www/.htsecure.* 2>/dev/null || echo 'none visible'
      echo '== cert =='
      for c in \$(\$SUDO find /etc/letsencrypt/live -name cert.pem 2>/dev/null); do \$SUDO openssl x509 -enddate -subject -noout -in \"\$c\"; done
      echo '== a7 systemd units =='
      ls /etc/systemd/system/a7-* 2>/dev/null || echo 'no a7-* units'
      systemctl list-timers 'a7-*' --all --no-pager 2>/dev/null | head -12 || true
      echo '== bitrix cron =='
      \$SUDO crontab -l -u bitrix 2>/dev/null | grep -v '^#' | head -12 || echo 'cron unreadable (sudo?)'
    "
    ;;

  a7)
    [[ $# -eq 0 ]] || die "a7 takes no arguments"
    remote "set -u
      SUDO=''; sudo -n true 2>/dev/null && SUDO='sudo -n'
      for d in /home/bitrix/www/bitrix/js /home/bitrix/www/bitrix/tools \
               /home/bitrix/www/bitrix/php_interface/include \
               /home/bitrix/www/local/php_interface/include; do
        echo \"== \$d ==\"
        \$SUDO ls -la --time-style=long-iso \"\$d\"/a7_* 2>/dev/null | awk '{print \$6, \$7, \$5, \$8}' || true
      done
      echo '== init.php =='
      \$SUDO ls -la --time-style=long-iso /home/bitrix/www/bitrix/php_interface/init.php 2>/dev/null || true
    "
    ;;

  counts)
    [[ $# -eq 0 ]] || die "counts takes no arguments"
    printf '%s' "SELECT COUNT(*) AS leads, MAX(ID) AS max_lead_id FROM b_crm_lead;
SELECT MAX(DATE_MODIFY) AS last_lead_modify, MAX(DATE_CREATE) AS last_lead_create FROM b_crm_lead;
SELECT COUNT(*) AS deals FROM b_crm_deal;
SELECT COUNT(*) AS timeline_rows, MAX(CREATED) AS last_timeline FROM b_crm_timeline;" | remote \
      "SUDO=''; sudo -n true 2>/dev/null && SUDO='sudo -n'; \
       \$SUDO mysql --batch --init-command='SET SESSION TRANSACTION READ ONLY' sitemanager 2>&1"
    ;;

  sql)
    query="${1:-}"
    [[ -n "$query" ]] || die "sql needs a query"
    # Read-only because the session says so, not because the query looked harmless.
    printf '%s' "$query" | remote \
      "SUDO=''; sudo -n true 2>/dev/null && SUDO='sudo -n'; \
       \$SUDO mysql --batch --init-command='SET SESSION TRANSACTION READ ONLY' sitemanager 2>&1"
    ;;

  md5)
    check_remote_path "${1:-}"
    remote "SUDO=''; sudo -n true 2>/dev/null && SUDO='sudo -n'; \$SUDO md5sum '$1'"
    ;;

  http)
    path="${1:-/}"
    [[ "$path" == /* ]] || die "http takes a path beginning with /"
    [[ "$path" =~ ^[A-Za-z0-9._/?=\&@-]+$ ]] || die "refusing unusual characters in: '$path'"
    remote "curl -sk -o /dev/null -w '%{http_code}  %{size_download} bytes\n' \
      -H 'Host: crm.a7grouprealestatedxb.com' 'https://127.0.0.1$path'"
    ;;

  put)
    local_path="${1:-}"; remote_path="${2:-}"
    [[ -f "$local_path" ]] || die "no such local file: '$local_path'"
    check_remote_path "$remote_path"
    tmpname="a7-bitrix-put-${RANDOM}-$$"
    scp.exe -i "$KEY" "${SSH_OPTS[@]}" "$local_path" "$HOST:/tmp/$tmpname"
    remote "set -u
      SUDO=''; sudo -n true 2>/dev/null && SUDO='sudo -n'
      [[ -n \"\$SUDO\" ]] || { echo 'sudo required to write'; exit 1; }
      \$SUDO cp /tmp/$tmpname '$remote_path'
      \$SUDO chown bitrix:bitrix '$remote_path' 2>/dev/null || true
      \$SUDO chmod 644 '$remote_path'
      rm -f /tmp/$tmpname
      \$SUDO md5sum '$remote_path'
    "
    ;;

  run)
    name="${1:-}"
    [[ "$name" =~ ^a7_[A-Za-z0-9_]+\.php$ ]] || die "run takes an a7_*.php filename"
    remote_path="/home/bitrix/www/local/php_interface/include/$name"
    check_remote_path "$remote_path"
    remote "set -u
      SUDO=''; sudo -n true 2>/dev/null && SUDO='sudo -n'
      [[ -n \"\$SUDO\" ]] || { echo 'sudo required'; exit 1; }
      \$SUDO test -f '$remote_path' || { echo 'missing $remote_path'; exit 1; }
      \$SUDO -u bitrix php '$remote_path'
    "
    ;;

  *)
    sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
