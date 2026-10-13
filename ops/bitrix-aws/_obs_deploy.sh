#!/bin/bash
set -euo pipefail
INIT=/home/bitrix/www/bitrix/php_interface/init.php
PHP_DST=/home/bitrix/www/bitrix/php_interface/include/a7_observer_filter.php
JS_DST=/home/bitrix/www/bitrix/js/a7_observer_filter.js
INC='require_once $_SERVER["DOCUMENT_ROOT"]."/bitrix/php_interface/include/a7_observer_filter.php";'

install -o bitrix -g bitrix -m 644 /tmp/a7_observer_filter.php "$PHP_DST"
install -o bitrix -g bitrix -m 644 /tmp/a7_observer_filter.js "$JS_DST"

python3 - <<'PY'
from pathlib import Path
p = Path("/home/bitrix/www/bitrix/php_interface/init.php")
t = p.read_text(encoding="utf-8", errors="replace")
needle = 'require_once $_SERVER["DOCUMENT_ROOT"]."/bitrix/php_interface/include/a7_observer_filter.php";'
if needle not in t:
    marker = 'a7_stage_admin.php'
    idx = t.find(marker)
    if idx == -1:
        t = t.rstrip() + "\n" + needle + "\n"
    else:
        line_end = t.find("\n", idx)
        t = t[:line_end+1] + needle + "\n" + t[line_end+1:]
    p.write_text(t, encoding="utf-8")
    print("INIT_PATCHED")
else:
    print("INIT_OK")
PY

php -l "$PHP_DST"
php -l "$INIT"
ls -la "$PHP_DST" "$JS_DST"
grep -n 'a7_observer_filter' "$INIT"
echo "==== observer user count ===="
sudo -u bitrix php -r '
$_SERVER["DOCUMENT_ROOT"]="/home/bitrix/www";
require "/home/bitrix/www/bitrix/modules/main/include/prolog_before.php";
$c = Bitrix\Main\Application::getConnection();
$n = $c->queryScalar("SELECT COUNT(DISTINCT USER_ID) FROM b_crm_observer WHERE ENTITY_TYPE_ID = 1");
$leads = $c->queryScalar("SELECT COUNT(DISTINCT ENTITY_ID) FROM b_crm_observer WHERE ENTITY_TYPE_ID = 1");
echo "observer_users=$n observer_leads=$leads\n";
'
echo DEPLOY_OK
