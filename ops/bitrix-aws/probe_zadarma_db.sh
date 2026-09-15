#!/usr/bin/env bash
set -eu
echo "=== settings db ==="
php -r '
$s = include "/home/bitrix/www/bitrix/.settings.php";
$db = $s["connections"]["value"]["default"] ?? [];
echo ($db["database"] ?? "?") . "\n";
echo ($db["login"] ?? "?") . "\n";
echo ($db["host"] ?? "?") . "\n";
' 2>/dev/null || true

DB=$(php -r '$s=include "/home/bitrix/www/bitrix/.settings.php"; echo $s["connections"]["value"]["default"]["database"]??"";' 2>/dev/null || true)
LOGIN=$(php -r '$s=include "/home/bitrix/www/bitrix/.settings.php"; echo $s["connections"]["value"]["default"]["login"]??"";' 2>/dev/null || true)
PASS=$(php -r '$s=include "/home/bitrix/www/bitrix/.settings.php"; echo $s["connections"]["value"]["default"]["password"]??"";' 2>/dev/null || true)
HOST=$(php -r '$s=include "/home/bitrix/www/bitrix/.settings.php"; echo $s["connections"]["value"]["default"]["host"]??"localhost";' 2>/dev/null || true)
echo "DB=$DB LOGIN=$LOGIN HOST=$HOST"

MYSQL="mysql -N -h${HOST} -u${LOGIN}"
if [ -n "$PASS" ]; then MYSQL="$MYSQL -p${PASS}"; fi

echo "=== rest events ==="
$MYSQL "$DB" -e "SELECT ID, EVENT_NAME, LEFT(EVENT_HANDLER,140), APP_ID FROM b_rest_event WHERE EVENT_NAME LIKE '%EXTERNAL%' OR EVENT_HANDLER LIKE '%voiso%' OR EVENT_HANDLER LIKE '%zadarma%' OR EVENT_HANDLER LIKE '%ams04%' OR LOWER(EVENT_HANDLER) LIKE '%click%' LIMIT 80;"

echo "=== rest apps ==="
$MYSQL "$DB" -e "SELECT ID, CODE, ACTIVE, LEFT(APP_NAME,90) FROM b_rest_app WHERE LOWER(APP_NAME) LIKE '%voiso%' OR LOWER(APP_NAME) LIKE '%zadarma%' OR LOWER(CODE) LIKE '%voiso%' OR LOWER(CODE) LIKE '%zadarma%' OR LOWER(APP_NAME) LIKE '%telephony%' OR LOWER(APP_NAME) LIKE '%cloud%' ORDER BY ID DESC LIMIT 50;"

echo "=== all active rest apps sample ==="
$MYSQL "$DB" -e "SELECT ID, CODE, ACTIVE, LEFT(APP_NAME,90) FROM b_rest_app WHERE ACTIVE='Y' ORDER BY ID DESC LIMIT 60;"

echo "=== telephony options ==="
$MYSQL "$DB" -e "SELECT MODULE_ID, NAME, LEFT(VALUE,180) FROM b_option WHERE MODULE_ID IN ('voximplant','telephony') OR NAME LIKE '%DEFAULT_LINE%' OR NAME LIKE '%PORTAL_NUMBER%' LIMIT 60;"

echo "=== file hits ==="
grep -ril 'voiso\|zadarma\|cc-ams04\|a7 cloud' /home/bitrix/www/bitrix/js /home/bitrix/www/local /home/bitrix/www/bitrix/php_interface /home/bitrix/www/bitrix/templates 2>/dev/null | head -60 || true

echo "=== live JS dial path ==="
grep -n '971\|normalizeDialPhone\|phoneTo\|Voiso\|Zadarma\|dialVia\|BXIM' /home/bitrix/www/bitrix/js/a7_owner_data_call.js | head -50 || true

echo "=== a7_clean_phone ==="
grep -n 'function a7_clean_phone\|971\|normalize' /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php | head -50 || true

echo "=== done ==="
