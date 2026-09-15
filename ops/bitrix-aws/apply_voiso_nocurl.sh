#!/bin/bash
set -euo pipefail
sed -i 's/\r$//' /tmp/fix_owner_voiso_nocurl.php
sudo -u bitrix php /tmp/fix_owner_voiso_nocurl.php

# Web probe: POST to Voiso via a7_http_raw (same path as fixed handler)
sudo tee /home/bitrix/www/bitrix/tools/_a7_voiso_http_probe.php >/dev/null <<'PHP'
<?php
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/tools/a7_3cx_click_to_call.php';

header('Content-Type: application/json');
$cfg = a7_voiso_click2call_config();
$payload = [
  'event' => 'ONEXTERNALCALLSTART',
  'event_handler_id' => $cfg['event_handler_id'],
  'data' => [
    'PHONE_NUMBER' => '+971551054133',
    'PHONE_NUMBER_INTERNATIONAL' => '+971551054133',
    'USER_ID' => '1',
    'CALL_ID' => 'externalCall.a7voiso.probe.' . time(),
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
    'application_token' => $cfg['application_token'],
  ],
];
$http = a7_http_raw(
  'POST',
  $cfg['url'],
  ['Content-Type' => 'application/x-www-form-urlencoded'],
  http_build_query($payload)
);
echo json_encode([
  'ok' => $http['ok'] ?? null,
  'status' => $http['status'] ?? null,
  'error' => $http['error'] ?? null,
  'raw' => mb_substr((string)($http['raw'] ?? ''), 0, 500),
  'handler_uses_http_raw' => strpos(file_get_contents(__DIR__ . '/a7_3cx_click_to_call.php'), "a7_http_raw(\n        'POST',\n        \$cfg['url']") !== false,
], JSON_UNESCAPED_SLASHES);
PHP
sudo chown bitrix:bitrix /home/bitrix/www/bitrix/tools/_a7_voiso_http_probe.php
sudo chmod 644 /home/bitrix/www/bitrix/tools/_a7_voiso_http_probe.php
echo "=== probe response ==="
curl -sS 'https://crm.a7grouprealestatedxb.com/bitrix/tools/_a7_voiso_http_probe.php'
echo
sudo rm -f /home/bitrix/www/bitrix/tools/_a7_voiso_http_probe.php
echo DONE
