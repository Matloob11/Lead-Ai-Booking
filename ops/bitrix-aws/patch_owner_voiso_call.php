<?php
/**
 * Patch live a7_3cx_click_to_call.php:
 * add owner-data-call-voiso action that POSTs to Voiso Bitrix click2call
 * without restoring Voiso on ONEXTERNALCALLSTART (keeps Zadarma phoneTo clean).
 */
$path = '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';
$src = file_get_contents($path);
if ($src === false) {
	fwrite(STDERR, "cannot read $path\n");
	exit(1);
}

if (str_contains($src, 'a7_handle_owner_data_call_voiso')) {
	echo "already patched\n";
	exit(0);
}

$helper = <<<'PHP'

function a7_voiso_click2call_config(): array
{
    // Restored from a7_rest_event_voiso_backup (event 786) — NOT re-registered
    // on ONEXTERNALCALLSTART so Zadarma phoneTo stays exclusive.
    return [
        'url' => 'https://cc-ams04.voiso.com/api/v2/bitrix/click2call',
        'application_token' => 'h41vbi4n0mqo0l2411h17ki21d4kj0lo',
        'event_handler_id' => '786',
    ];
}

function a7_handle_owner_data_call_voiso(): void
{
    $userId = a7_require_bitrix_user();
    $itemId = (int)a7_request_value('id', 0);
    $phone = a7_owner_data_normalize_phone_value((string)a7_request_value('phone', ''));
    $pageUrl = (string)a7_request_value('pageUrl', '');

    if ($itemId <= 0) {
        a7_json(['success' => false, 'message' => 'Owner Data item id missing'], 400);
    }
    if ($phone === '' || strpos($phone, '+971') !== 0) {
        a7_json(['success' => false, 'message' => 'Valid UAE phone (+971…) missing'], 400);
    }

    $item = a7_owner_data_get_item($itemId);
    if ($item === null) {
        a7_json(['success' => false, 'message' => 'Owner Data item not found'], 404);
    }

    $phones = a7_owner_data_collect_phones($item);
    $allowed = false;
    foreach ($phones as $row) {
        $a = preg_replace('/\D/', '', (string)$row['phone']) ?? '';
        $b = preg_replace('/\D/', '', $phone) ?? '';
        if ($a !== '' && $b !== '' && (substr($a, -10) === substr($b, -10) || $a === $b)) {
            $allowed = true;
            $phone = (string)$row['phone'];
            break;
        }
    }
    if (!$allowed) {
        a7_json(['success' => false, 'message' => 'Phone is not on this Owner Data card'], 400);
    }

    $cfg = a7_voiso_click2call_config();
    $callId = 'externalCall.a7voiso.' . $userId . '.' . time();

    // Register in Bitrix telephony so CRM timeline gets a call id (best-effort).
    $reg = a7_bitrix_webhook_call('telephony.externalcall.register', [
        'USER_ID' => $userId,
        'PHONE_NUMBER' => $phone,
        'TYPE' => 1,
        'CRM_CREATE' => 0,
        'CRM_ENTITY_TYPE' => 'DYNAMIC_' . A7_OWNER_DATA_ENTITY_TYPE_ID,
        'CRM_ENTITY_ID' => $itemId,
        'SHOW' => 0,
    ]);
    if (!empty($reg['ok']) && is_array($reg['json']['result'] ?? null)) {
        $callId = (string)($reg['json']['result']['CALL_ID'] ?? $callId);
    }

    $domain = (string)($_SERVER['SERVER_NAME'] ?? 'crm.a7grouprealestatedxb.com');
    $payload = [
        'event' => 'ONEXTERNALCALLSTART',
        'event_handler_id' => $cfg['event_handler_id'],
        'data' => [
            'PHONE_NUMBER' => $phone,
            'PHONE_NUMBER_INTERNATIONAL' => $phone,
            'EXTENSION' => '',
            'USER_ID' => (string)$userId,
            'CALL_LIST_ID' => '0',
            'LINE_NUMBER' => '',
            'IS_MOBILE' => '0',
            'CALL_ID' => $callId,
            'CRM_ENTITY_TYPE' => 'DYNAMIC_' . A7_OWNER_DATA_ENTITY_TYPE_ID,
            'CRM_ENTITY_ID' => (string)$itemId,
            'PAGE_URL' => $pageUrl,
        ],
        'ts' => (string)time(),
        'auth' => [
            'domain' => $domain,
            'client_endpoint' => 'https://' . $domain . '/rest/',
            'server_endpoint' => 'https://oauth.bitrix.info/rest/',
            'member_id' => '',
            'application_token' => $cfg['application_token'],
        ],
    ];

    // Apache PHP on this host has curl disabled; a7_http_raw falls back to streams.
    $http = a7_http_raw(
        'POST',
        $cfg['url'],
        ['Content-Type' => 'application/x-www-form-urlencoded'],
        http_build_query($payload)
    );
    $raw = (string)($http['raw'] ?? '');
    $status = (int)($http['status'] ?? 0);
    $error = (string)($http['error'] ?? '');

    if (empty($http['ok'])) {
        a7_log('owner-data voiso click2call failed', [
            'item_id' => $itemId,
            'phone' => a7_mask_phone($phone),
            'http' => $status,
            'error' => $error,
            'raw' => mb_substr($raw, 0, 400),
        ]);
        a7_json([
            'success' => false,
            'message' => 'Voiso rejected the call (' . ($status ?: 'net') . '). Be Available in Voiso Agent Panel.',
            'http' => $status,
            'detail' => mb_substr($raw !== '' ? $raw : $error, 0, 180),
        ], 502);
    }

    a7_bitrix_webhook_call('crm.activity.add', [
        'fields' => [
            'OWNER_TYPE_ID' => A7_OWNER_DATA_ENTITY_TYPE_ID,
            'OWNER_ID' => $itemId,
            'TYPE_ID' => 2,
            'SUBJECT' => 'Owner Data Voiso call started',
            'START_TIME' => date('c'),
            'END_TIME' => date('c'),
            'COMPLETED' => 'N',
            'DIRECTION' => 2,
            'RESPONSIBLE_ID' => $userId,
            'DESCRIPTION' => "Voiso outbound call started.\nPhone: {$phone}\nCall ID: {$callId}",
            'COMMUNICATIONS' => [[
                'ENTITY_TYPE_ID' => A7_OWNER_DATA_ENTITY_TYPE_ID,
                'ENTITY_ID' => $itemId,
                'TYPE' => 'PHONE',
                'VALUE' => $phone,
            ]],
        ],
    ]);

    a7_log('owner-data voiso click2call started', [
        'item_id' => $itemId,
        'phone' => a7_mask_phone($phone),
        'bitrix_user_id' => $userId,
        'call_id' => $callId,
        'http' => $status,
    ]);

    a7_json([
        'success' => true,
        'message' => 'Voiso call started',
        'phone' => $phone,
        'callId' => $callId,
        'provider' => 'voiso',
        'itemId' => $itemId,
    ]);
}

PHP;

$marker = '/* === END A7_OWNER_DATA_CUSTOM_CALL HELPERS === */';
if (!str_contains($src, $marker)) {
	fwrite(STDERR, "END marker missing\n");
	exit(1);
}
$src = str_replace($marker, $helper . "\n" . $marker, $src);

$routeNeedle = "    if (\$action === 'owner-data-call') {\n        a7_handle_owner_data_call();\n    }";
$routeInsert = $routeNeedle . "\n\n    if (\$action === 'owner-data-call-voiso') {\n        a7_handle_owner_data_call_voiso();\n    }";
if (!str_contains($src, $routeNeedle)) {
	fwrite(STDERR, "route needle missing\n");
	exit(1);
}
if (!str_contains($src, "owner-data-call-voiso")) {
	$src = str_replace($routeNeedle, $routeInsert, $src);
}

$bak = $path . '.bak-voiso-' . date('Ymd-His');
if (!copy($path, $bak)) {
	fwrite(STDERR, "backup failed\n");
	exit(1);
}
if (file_put_contents($path, $src) === false) {
	fwrite(STDERR, "write failed\n");
	exit(1);
}

echo "patched ok backup=$bak\n";
echo "has_fn=" . (str_contains($src, 'a7_handle_owner_data_call_voiso') ? 'Y' : 'N') . "\n";
echo "has_route=" . (str_contains($src, "owner-data-call-voiso") ? 'Y' : 'N') . "\n";
