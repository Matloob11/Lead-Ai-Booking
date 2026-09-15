<?php
/**
 * Patch live Bitrix for Sales Deals (category 1) dual Call:
 * - deal-phones accepts CATEGORY_ID=1 (contact phones)
 * - deal-call-voiso → Voiso click2call (same as Owner Data)
 * - init.php injects a7_deals_call.js on /crm/deal/
 */
$path = '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';
$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$jsSrc = '/tmp/a7_deals_call.js';
$jsDst = '/home/bitrix/www/bitrix/js/a7_deals_call.js';

$src = file_get_contents($path);
if ($src === false) {
    fwrite(STDERR, "cannot read $path\n");
    exit(1);
}
if (!is_readable($jsSrc)) {
    fwrite(STDERR, "missing $jsSrc\n");
    exit(1);
}

$stamp = date('Ymd-His');
copy($path, $path . '.bak.deals-call-' . $stamp);
copy($init, $init . '.bak.deals-call-' . $stamp);

$helpers = <<<'PHP'

/* === BEGIN A7_SALES_DEALS_CUSTOM_CALL HELPERS === */
function a7_sales_deal_category_id(): int
{
    return 1;
}

function a7_sales_deal_collect_phones(array $deal): array
{
    $out = [];
    $seen = [];

    $push = static function (string $phone, string $label, string $field) use (&$out, &$seen): void {
        $digits = preg_replace('/\D/', '', $phone) ?? '';
        if (strlen($digits) < 6) {
            return;
        }
        $key = strlen($digits) > 10 ? substr($digits, -10) : $digits;
        if (isset($seen[$key])) {
            return;
        }
        $seen[$key] = true;
        $out[] = [
            'phone' => $phone,
            'label' => $label,
            'field' => $field,
        ];
    };

    $contactId = (int)($deal['CONTACT_ID'] ?? 0);
    if ($contactId > 0) {
        $contactResp = a7_bitrix_webhook_call('crm.contact.get', ['id' => $contactId]);
        $contact = $contactResp['json']['result'] ?? null;
        if (!empty($contactResp['ok']) && is_array($contact)) {
            $phoneRows = $contact['PHONE'] ?? [];
            if (!is_array($phoneRows)) {
                $phoneRows = [];
            }
            foreach ($phoneRows as $row) {
                if (!is_array($row)) {
                    continue;
                }
                $raw = (string)($row['VALUE'] ?? '');
                $phone = function_exists('a7_owner_data_normalize_phone_value')
                    ? a7_owner_data_normalize_phone_value($raw)
                    : a7_clean_phone($raw);
                $type = (string)($row['VALUE_TYPE'] ?? 'WORK');
                $push($phone, 'Contact phone (' . $type . ')', 'CONTACT_PHONE');
            }
        }
    }

    $companyId = (int)($deal['COMPANY_ID'] ?? 0);
    if ($companyId > 0) {
        $companyResp = a7_bitrix_webhook_call('crm.company.get', ['id' => $companyId]);
        $company = $companyResp['json']['result'] ?? null;
        if (!empty($companyResp['ok']) && is_array($company)) {
            $phoneRows = $company['PHONE'] ?? [];
            if (!is_array($phoneRows)) {
                $phoneRows = [];
            }
            foreach ($phoneRows as $row) {
                if (!is_array($row)) {
                    continue;
                }
                $raw = (string)($row['VALUE'] ?? '');
                $phone = function_exists('a7_owner_data_normalize_phone_value')
                    ? a7_owner_data_normalize_phone_value($raw)
                    : a7_clean_phone($raw);
                $type = (string)($row['VALUE_TYPE'] ?? 'WORK');
                $push($phone, 'Company phone (' . $type . ')', 'COMPANY_PHONE');
            }
        }
    }

    return $out;
}

function a7_handle_deal_call_voiso(): void
{
    $userId = a7_require_bitrix_user();
    $dealId = (int)a7_request_value('id', 0);
    $phone = function_exists('a7_owner_data_normalize_phone_value')
        ? a7_owner_data_normalize_phone_value((string)a7_request_value('phone', ''))
        : a7_clean_phone((string)a7_request_value('phone', ''));
    $pageUrl = (string)a7_request_value('pageUrl', '');

    if ($dealId <= 0) {
        a7_json(['success' => false, 'message' => 'Deal id missing'], 400);
    }
    if ($phone === '' || strpos($phone, '+971') !== 0) {
        a7_json(['success' => false, 'message' => 'Valid UAE phone (+971…) missing'], 400);
    }

    $deal = a7_deal_get($dealId);
    if ($deal === null) {
        a7_json(['success' => false, 'message' => 'Deal not found'], 404);
    }

    $categoryId = (int)($deal['CATEGORY_ID'] ?? 0);
    if ($categoryId === a7_renewals_category_id()) {
        $phones = a7_deal_collect_phones($deal);
    } elseif ($categoryId === a7_sales_deal_category_id()) {
        $phones = a7_sales_deal_collect_phones($deal);
    } else {
        a7_json(['success' => false, 'message' => 'Call buttons are only for Sales or Renewals deals'], 400);
    }

    $allowed = false;
    foreach ($phones as $row) {
        $a = preg_replace('/\D/', '', (string)$row['phone']) ?? '';
        $b = preg_replace('/\D/', '', $phone) ?? '';
        if ($a !== '' && $b !== '' && (substr($a, -10) === substr($b, -10) || $a === $b)) {
            $allowed = true;
            $phone = (string)$row['phone'];
            if (strpos($phone, '+') !== 0) {
                $phone = function_exists('a7_owner_data_normalize_phone_value')
                    ? a7_owner_data_normalize_phone_value($phone)
                    : ('+' . preg_replace('/\D/', '', $phone));
            }
            break;
        }
    }
    if (!$allowed) {
        a7_json(['success' => false, 'message' => 'Phone is not on this deal / linked contact'], 400);
    }

    if (!function_exists('a7_voiso_click2call_config')) {
        a7_json(['success' => false, 'message' => 'Voiso config missing'], 500);
    }
    $cfg = a7_voiso_click2call_config();
    $callId = 'externalCall.a7voiso.deal.' . $userId . '.' . time();

    $reg = a7_bitrix_webhook_call('telephony.externalcall.register', [
        'USER_ID' => $userId,
        'PHONE_NUMBER' => $phone,
        'TYPE' => 1,
        'CRM_CREATE' => 0,
        'CRM_ENTITY_TYPE' => 'DEAL',
        'CRM_ENTITY_ID' => $dealId,
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
            'CRM_ENTITY_TYPE' => 'DEAL',
            'CRM_ENTITY_ID' => (string)$dealId,
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
        a7_log('deal voiso click2call failed', [
            'deal_id' => $dealId,
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
            'OWNER_TYPE_ID' => 2,
            'OWNER_ID' => $dealId,
            'TYPE_ID' => 2,
            'SUBJECT' => 'Deal Voiso call started',
            'START_TIME' => date('c'),
            'END_TIME' => date('c'),
            'COMPLETED' => 'N',
            'DIRECTION' => 2,
            'RESPONSIBLE_ID' => $userId,
            'DESCRIPTION' => "Voiso outbound call started.\nPhone: {$phone}\nCall ID: {$callId}",
            'COMMUNICATIONS' => [[
                'ENTITY_TYPE_ID' => 2,
                'ENTITY_ID' => $dealId,
                'TYPE' => 'PHONE',
                'VALUE' => $phone,
            ]],
        ],
    ]);

    a7_log('deal voiso click2call started', [
        'deal_id' => $dealId,
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
        'dealId' => $dealId,
    ]);
}
/* === END A7_SALES_DEALS_CUSTOM_CALL HELPERS === */

PHP;

if (!str_contains($src, 'A7_SALES_DEALS_CUSTOM_CALL HELPERS')) {
    $needle = '/* === END A7_RENEWALS_CUSTOM_CALL HELPERS === */';
    if (!str_contains($src, $needle)) {
        fwrite(STDERR, "renewals end marker missing\n");
        exit(1);
    }
    $src = str_replace($needle, $needle . "\n" . $helpers, $src);
    echo "helpers inserted\n";
} else {
    echo "helpers already present\n";
}

// Widen deal-phones to accept sales category 1.
$oldBlock = <<<'PHP'
    $categoryId = (int)($deal['CATEGORY_ID'] ?? 0);
    if ($categoryId !== a7_renewals_category_id()) {
        a7_json([
            'success' => true,
            'skipped' => true,
            'reason' => 'not_renewals_category',
            'categoryId' => $categoryId,
            'phones' => [],
            'count' => 0,
        ]);
    }

    $phones = a7_deal_collect_phones($deal);
PHP;

$newBlock = <<<'PHP'
    $categoryId = (int)($deal['CATEGORY_ID'] ?? 0);
    if ($categoryId === a7_renewals_category_id()) {
        $phones = a7_deal_collect_phones($deal);
    } elseif (function_exists('a7_sales_deal_category_id') && $categoryId === a7_sales_deal_category_id()) {
        $phones = a7_sales_deal_collect_phones($deal);
    } else {
        a7_json([
            'success' => true,
            'skipped' => true,
            'reason' => 'unsupported_deal_category',
            'categoryId' => $categoryId,
            'phones' => [],
            'count' => 0,
        ]);
    }
PHP;

if (str_contains($src, 'unsupported_deal_category') || str_contains($src, 'a7_sales_deal_collect_phones($deal)')) {
    echo "deal-phones already widened\n";
} elseif (str_contains($src, $oldBlock)) {
    $src = str_replace($oldBlock, $newBlock, $src);
    echo "deal-phones widened\n";
} else {
    // Fallback: softer replace around skipped reason.
    if (str_contains($src, "'reason' => 'not_renewals_category'")) {
        $src = preg_replace(
            '/\$categoryId = \(int\)\(\$deal\[\'CATEGORY_ID\'\] \?\? 0\);\s*if \(\$categoryId !== a7_renewals_category_id\(\)\) \{.*?\$phones = a7_deal_collect_phones\(\$deal\);/s',
            trim($newBlock),
            $src,
            1,
            $count
        );
        echo $count ? "deal-phones widened via regex\n" : "WARN deal-phones widen failed\n";
    } else {
        echo "WARN deal-phones pattern not found\n";
    }
}

if (!str_contains($src, "deal-call-voiso")) {
    $routeNeedle = "    if (\$action === 'deal-phones') {\n        a7_handle_deal_phones();\n    }";
    if (!str_contains($src, $routeNeedle)) {
        fwrite(STDERR, "deal-phones route needle missing\n");
        exit(1);
    }
    $src = str_replace(
        $routeNeedle,
        $routeNeedle . "\n\n    if (\$action === 'deal-call-voiso') {\n        a7_handle_deal_call_voiso();\n    }",
        $src
    );
    echo "route deal-call-voiso added\n";
} else {
    echo "route deal-call-voiso already present\n";
}

if (file_put_contents($path, $src) === false) {
    fwrite(STDERR, "write php failed\n");
    exit(1);
}

if (!copy($jsSrc, $jsDst)) {
    fwrite(STDERR, "copy js failed\n");
    exit(1);
}
@chown(fileowner('/home/bitrix/www/bitrix/js/a7_owner_data_call.js') ?: 'bitrix', $jsDst);
@chmod($jsDst, 0644);
echo "js copied " . filesize($jsDst) . "\n";

$initSrc = file_get_contents($init);
if ($initSrc === false) {
    fwrite(STDERR, "cannot read init\n");
    exit(1);
}
if (!str_contains($initSrc, 'A7_SALES_DEALS_CUSTOM_CALL')) {
    $block = <<<'PHP'

// A7_SALES_DEALS_CUSTOM_CALL: Sales deals (category 1) Zadarma + Voiso Call buttons.
if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', static function () {
        global $APPLICATION, $USER;
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        if (strpos($uri, '/crm/deal/') !== 0) {
            return;
        }
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
            return;
        }
        $scriptPath = '/bitrix/js/a7_deals_call.js';
        $fullPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $scriptPath;
        $version = is_readable($fullPath) ? (string)@filemtime($fullPath) : (string)time();
        $APPLICATION->AddHeadScript($scriptPath . '?v=' . $version);
    });
}

PHP;
    $initSrc = rtrim($initSrc) . "\n" . $block . "\n";
    if (file_put_contents($init, $initSrc) === false) {
        fwrite(STDERR, "write init failed\n");
        exit(1);
    }
    echo "init patched\n";
} else {
    echo "init already patched\n";
}

passthru('php -l ' . escapeshellarg($path), $code1);
passthru('php -l ' . escapeshellarg($init), $code2);
echo "has_sales_helpers=" . (str_contains(file_get_contents($path), 'a7_sales_deal_collect_phones') ? 'Y' : 'N') . "\n";
echo "has_voiso_route=" . (str_contains(file_get_contents($path), 'deal-call-voiso') ? 'Y' : 'N') . "\n";
echo "js_http=";
passthru('curl -sI https://crm.a7grouprealestatedxb.com/bitrix/js/a7_deals_call.js | head -n 1');
exit(($code1 === 0 && $code2 === 0) ? 0 : 1);
