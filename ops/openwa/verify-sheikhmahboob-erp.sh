#!/usr/bin/env bash
set -euo pipefail
SITE=187.127.123.235
BENCH=/home/frappe/frappe-bench
python3 - <<'PY'
import json
c = json.load(open("/home/frappe/frappe-bench/sites/187.127.123.235/site_config.json"))
print("host_name=", c.get("host_name"))
print("domains=", c.get("domains"))
PY
sudo -u frappe bash -lc "cd '$BENCH' && bench setup add-domain sheikhmahboob.com --site $SITE" || true
sudo -u frappe bash -lc "cd '$BENCH' && bench setup add-domain www.sheikhmahboob.com --site $SITE" || true
sudo -u frappe bash -lc "cd '$BENCH' && bench --site $SITE set-config host_name https://sheikhmahboob.com"
sudo -u frappe bash -lc "cd '$BENCH' && bench --site $SITE clear-cache" || true
python3 - <<'PY'
import json
c = json.load(open("/home/frappe/frappe-bench/sites/187.127.123.235/site_config.json"))
print("after host_name=", c.get("host_name"))
print("after domains=", c.get("domains"))
PY
echo "=== curl ==="
curl -sS -o /dev/null -w 'https=%{http_code}\n' https://sheikhmahboob.com/
curl -sS -I https://sheikhmahboob.com/ | head -12
