#!/bin/bash
set -euo pipefail

echo "=== find curl.so ==="
find /usr -name '*curl*.so' 2>/dev/null | head -20 || true

echo "=== php modules locations ==="
ls /etc/php.d/*curl* 2>/dev/null || true
ls /etc/php/*/mods-available/*curl* 2>/dev/null || true
ls /etc/php/*/fpm/conf.d/*curl* 2>/dev/null || true

echo "=== php-fpm process ==="
ps aux | grep -E 'php-fpm|httpd|nginx' | grep -v grep | head -20

echo "=== try bitrix php if any ==="
ls -la /home/bitrix/www/bitrix/modules/main/tools/php 2>/dev/null || true
command -v php82 || true
command -v php8.2 || true

echo "=== a7_log function ==="
grep -n 'function a7_log\|A7_.*LOG\|click_to_call.log' /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php | head -20
sed -n '180,250p' /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php

echo "=== voiso backup ==="
mysql bitrix -e 'SELECT * FROM a7_rest_event_voiso_backup\G' || true
mysql bitrix -e 'SHOW COLUMNS FROM a7_rest_event_voiso_backup;' || true

echo "=== log file ==="
ls -la /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.log /var/log/php* 2>/dev/null || true
tail -n 50 /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.log 2>/dev/null || true

echo "=== web curl via temporary endpoint ==="
cat > /home/bitrix/www/bitrix/tools/_a7_curl_probe.php <<'PHP'
<?php
header('Content-Type: text/plain');
echo 'sapi=' . php_sapi_name() . "\n";
echo 'curl=' . (function_exists('curl_init') ? 'Y' : 'N') . "\n";
echo 'ver=' . PHP_VERSION . "\n";
if (function_exists('curl_init')) {
  $ch = curl_init('https://cc-ams04.voiso.com/api/v2/bitrix/click2call');
  curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 15,
    CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded'],
    CURLOPT_POSTFIELDS => http_build_query([
      'event' => 'ONEXTERNALCALLSTART',
      'event_handler_id' => '786',
      'data' => [
        'PHONE_NUMBER' => '+971551054133',
        'PHONE_NUMBER_INTERNATIONAL' => '+971551054133',
        'USER_ID' => '1',
        'CALL_ID' => 'externalCall.a7voiso.test.' . time(),
        'CRM_ENTITY_TYPE' => 'DYNAMIC_1042',
        'CRM_ENTITY_ID' => '89539',
        'IS_MOBILE' => '0',
      ],
      'ts' => (string) time(),
      'auth' => [
        'domain' => 'crm.a7grouprealestatedxb.com',
        'client_endpoint' => 'https://crm.a7grouprealestatedxb.com/rest/',
        'server_endpoint' => 'https://oauth.bitrix.info/rest/',
        'member_id' => '',
        'application_token' => 'h41vbi4n0mqo0l2411h17ki21d4kj0lo',
      ],
    ]),
  ]);
  $raw = curl_exec($ch);
  $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
  $err = curl_error($ch);
  curl_close($ch);
  echo "http=$status err=$err\n";
  echo "raw=" . substr((string) $raw, 0, 500) . "\n";
}
PHP
chown bitrix:bitrix /home/bitrix/www/bitrix/tools/_a7_curl_probe.php
chmod 644 /home/bitrix/www/bitrix/tools/_a7_curl_probe.php
curl -sS 'https://crm.a7grouprealestatedxb.com/bitrix/tools/_a7_curl_probe.php' || curl -sS 'http://127.0.0.1/bitrix/tools/_a7_curl_probe.php' || true
rm -f /home/bitrix/www/bitrix/tools/_a7_curl_probe.php
echo
echo DONE
