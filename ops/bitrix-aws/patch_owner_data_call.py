#!/usr/bin/env python3
"""Patch a7_3cx_click_to_call.php for Owner Data custom call (phones + dial).

Safe, idempotent. Does not enable global click-to-call — only Owner Data actions.
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PHP_PATH = Path("/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php")
INIT_PATH = Path("/home/bitrix/www/bitrix/php_interface/init.php")
JS_SRC = Path("/tmp/a7-od-call/a7_owner_data_call.js")
JS_DST = Path("/home/bitrix/www/bitrix/js/a7_owner_data_call.js")

MARKER = "A7_OWNER_DATA_CUSTOM_CALL"

PHONE_FIELDS_FN = r'''function a7_owner_data_phone_fields(): array
{
    return [
        'ufCrm5_1768317611513' => 'phone number',
        'ufCrm5_1769416533028' => 'phone number 1',
        'ufCrm5_1768314841508' => 'Import Owner Mobile',
        'ufCrm5_1768317656051' => 'mobile number 2',
        'ufCrm5_1777563197150' => 'Owner no 1',
        'ufCrm5_1779805546251' => 'Owner phone extra',
    ];
}
'''

HELPERS = r'''
/* === BEGIN ''' + MARKER + r''' HELPERS === */
function a7_owner_data_normalize_phone_value($raw): string
{
    if ($raw === null) {
        return '';
    }
    if (is_array($raw)) {
        foreach ($raw as $part) {
            $phone = a7_owner_data_normalize_phone_value($part);
            if ($phone !== '') {
                return $phone;
            }
        }
        return '';
    }
    $text = trim((string)$raw);
    if ($text === '' || $text === '0') {
        return '';
    }
    return a7_clean_phone($text);
}

function a7_owner_data_collect_phones(array $item): array
{
    $out = [];
    $seen = [];
    foreach (a7_owner_data_phone_fields() as $field => $label) {
        $value = $item[$field] ?? null;
        $values = is_array($value) ? $value : [$value];
        foreach ($values as $candidate) {
            $phone = a7_owner_data_normalize_phone_value($candidate);
            if ($phone === '') {
                continue;
            }
            $digits = preg_replace('/\D/', '', $phone) ?? '';
            if (strlen($digits) < 6) {
                continue;
            }
            $key = strlen($digits) > 10 ? substr($digits, -10) : $digits;
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $out[] = [
                'phone' => $phone,
                'label' => $label,
                'field' => $field,
            ];
        }
    }
    return $out;
}

function a7_owner_data_get_item(int $itemId): ?array
{
    if ($itemId <= 0) {
        return null;
    }
    $response = a7_bitrix_webhook_call('crm.item.get', [
        'entityTypeId' => A7_OWNER_DATA_ENTITY_TYPE_ID,
        'id' => $itemId,
    ]);
    $item = $response['json']['result']['item'] ?? null;
    if (!$response['ok'] || !is_array($item)) {
        return null;
    }
    return $item;
}

function a7_handle_owner_data_phones(): void
{
    a7_require_bitrix_user();
    $itemId = (int)a7_request_value('id', 0);
    if ($itemId <= 0) {
        a7_json(['success' => false, 'message' => 'Owner Data item id missing'], 400);
    }

    $item = a7_owner_data_get_item($itemId);
    if ($item === null) {
        a7_json(['success' => false, 'message' => 'Owner Data item not found'], 404);
    }

    $phones = a7_owner_data_collect_phones($item);
    a7_json([
        'success' => true,
        'itemId' => $itemId,
        'title' => (string)($item['title'] ?? ''),
        'categoryId' => (int)($item['categoryId'] ?? 0),
        'phones' => $phones,
        'count' => count($phones),
    ]);
}

function a7_handle_owner_data_call(): void
{
    // Owner Data only — independent of global A7_CALL_FEATURES_ENABLED.
    $userId = a7_require_bitrix_user();
    $itemId = (int)a7_request_value('id', 0);
    $phone = a7_clean_phone((string)a7_request_value('phone', ''));
    $pageUrl = (string)a7_request_value('pageUrl', '');

    if ($itemId <= 0) {
        a7_json(['success' => false, 'message' => 'Owner Data item id missing'], 400);
    }
    if ($phone === '' || strlen(preg_replace('/\D/', '', $phone) ?? '') < 6) {
        a7_json(['success' => false, 'message' => 'Valid phone number missing'], 400);
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
            break;
        }
    }
    if (!$allowed) {
        a7_json(['success' => false, 'message' => 'Phone is not on this Owner Data card'], 400);
    }

    try {
        $assignedById = (int)($item['assignedById'] ?? 0);
        $callOwner = a7_resolve_owner_extension('', 0, $assignedById > 0 ? $assignedById : $userId);
        // Prefer current logged-in agent's extension for click-to-call UX.
        $selfOwner = a7_resolve_owner_extension('', 0, $userId);
        $callOwner = $selfOwner;

        $makeCall = a7_3cx_make_call($phone, [
            'source' => 'owner_data_custom_button',
            'bitrix_user_id' => $userId,
            'call_owner_user_id' => $callOwner['bitrix_user_id'],
            'call_owner_email' => $callOwner['email'],
            'entity_type' => 'owner_data',
            'entity_id' => $itemId,
            'page_url' => $pageUrl,
        ], $callOwner['extension']);

        if (!$makeCall['ok']) {
            a7_log('owner-data 3CX makecall failed', [
                'phone' => $phone,
                'item_id' => $itemId,
                'extension' => $callOwner['extension'],
                'status' => $makeCall['status'],
                'raw' => (string)$makeCall['raw'],
            ]);
            a7_json(['success' => false, 'message' => '3CX makecall failed'], 502);
        }

        // Log activity on SPA item (entity type 1042).
        $description = '3CX outbound call started from Owner Data custom button.'
            . "\nExtension: " . $callOwner['extension']
            . "\nPhone: " . $phone;
        a7_bitrix_webhook_call('crm.activity.add', [
            'fields' => [
                'OWNER_TYPE_ID' => A7_OWNER_DATA_ENTITY_TYPE_ID,
                'OWNER_ID' => $itemId,
                'TYPE_ID' => 2,
                'SUBJECT' => 'Owner Data outbound call started',
                'START_TIME' => date('c'),
                'END_TIME' => date('c'),
                'COMPLETED' => 'N',
                'DIRECTION' => 2,
                'RESPONSIBLE_ID' => $callOwner['bitrix_user_id'],
                'DESCRIPTION' => $description,
                'COMMUNICATIONS' => [[
                    'ENTITY_TYPE_ID' => A7_OWNER_DATA_ENTITY_TYPE_ID,
                    'ENTITY_ID' => $itemId,
                    'TYPE' => 'PHONE',
                    'VALUE' => $phone,
                ]],
            ],
        ]);

        a7_log('owner-data 3CX makecall started', [
            'phone' => $phone,
            'item_id' => $itemId,
            'bitrix_user_id' => $userId,
            'extension' => $callOwner['extension'],
            'threecx_status' => $makeCall['status'],
        ]);

        a7_json([
            'success' => true,
            'message' => '3CX call started',
            'phone' => $phone,
            'extension' => $callOwner['extension'],
            'call_owner_user_id' => $callOwner['bitrix_user_id'],
            'call_owner_name' => $callOwner['name'],
            'itemId' => $itemId,
        ]);
    } catch (Throwable $e) {
        a7_log('owner-data call exception', ['error' => $e->getMessage(), 'item_id' => $itemId]);
        a7_json(['success' => false, 'message' => $e->getMessage()], 500);
    }
}
/* === END ''' + MARKER + r''' HELPERS === */
'''

ROUTE_SNIPPET = f'''
    if ($action === 'owner-data-phones') {{
        a7_handle_owner_data_phones();
    }}

    if ($action === 'owner-data-call') {{
        a7_handle_owner_data_call();
    }}
'''

INIT_BLOCK = r'''
// ''' + MARKER + r''': Owner Data (SPA 1042) custom Call button.
if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', static function () {
        global $APPLICATION, $USER;
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        if (strpos($uri, '/crm/type/1042/') !== 0) {
            return;
        }
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
            return;
        }
        $scriptPath = '/bitrix/js/a7_owner_data_call.js';
        $fullPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $scriptPath;
        $version = is_readable($fullPath) ? (string)@filemtime($fullPath) : (string)time();
        $APPLICATION->AddHeadScript($scriptPath . '?v=' . $version);
    });
}
'''


def backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_suffix(path.suffix + f".bak.{stamp}")
    shutil.copy2(path, bak)
    print(f"backup {bak}")
    return bak


def patch_php(text: str) -> str:
    if MARKER + " HELPERS" in text and "owner-data-call" in text and "a7_handle_owner_data_phones" in text:
        print("php helpers/routes already present")
    else:
        # Replace phone fields function
        text2, n = re.subn(
            r"function a7_owner_data_phone_fields\(\): array\s*\{.*?^\}\s*",
            PHONE_FIELDS_FN + "\n",
            text,
            count=1,
            flags=re.S | re.M,
        )
        if n != 1:
            raise SystemExit(f"phone fields replace failed n={n}")
        text = text2

        if MARKER + " HELPERS" not in text:
            # Insert helpers before a7_handle_owner_data_diagnostic
            needle = "function a7_handle_owner_data_diagnostic(): void"
            if needle not in text:
                raise SystemExit("diagnostic function not found")
            text = text.replace(needle, HELPERS + "\n" + needle, 1)

        if "owner-data-call" not in text:
            # Insert routes before owner-data-diagnostic route or at end of router
            diag_route = "if ($action === 'owner-data-diagnostic') {"
            if diag_route not in text:
                raise SystemExit("diagnostic route not found")
            text = text.replace(diag_route, ROUTE_SNIPPET + "\n    " + diag_route, 1)

        # Diagnostic should accept any Owner Data item (not only cat 14)
        text = text.replace(
            "if (!$response['ok'] || !is_array($item) || (int)($item['categoryId'] ?? 0) !== A7_OWNER_DATA_CATEGORY_ID) {\n"
            "        a7_json(['success' => false, 'message' => 'Owner Data item not found in category 14'], 404);\n"
            "    }",
            "if (!$response['ok'] || !is_array($item)) {\n"
            "        a7_json(['success' => false, 'message' => 'Owner Data item not found'], 404);\n"
            "    }",
            1,
        )

    return text


def patch_init(text: str) -> str:
    if MARKER in text:
        print("init already patched")
        return text
    return text.rstrip() + "\n" + INIT_BLOCK + "\n"


def main() -> int:
    if not PHP_PATH.is_file():
        raise SystemExit(f"missing {PHP_PATH}")
    if not JS_SRC.is_file():
        raise SystemExit(f"missing {JS_SRC}")

    backup(PHP_PATH)
    php = PHP_PATH.read_text(encoding="utf-8", errors="replace")
    PHP_PATH.write_text(patch_php(php), encoding="utf-8")
    print(f"patched {PHP_PATH}")

    backup(INIT_PATH)
    init = INIT_PATH.read_text(encoding="utf-8", errors="replace")
    INIT_PATH.write_text(patch_init(init), encoding="utf-8")
    print(f"patched {INIT_PATH}")

    shutil.copy2(JS_SRC, JS_DST)
    print(f"copied {JS_DST} ({JS_DST.stat().st_size} bytes)")

    # syntax check
    import subprocess

    for path in (PHP_PATH, INIT_PATH):
        r = subprocess.run(["php", "-l", str(path)], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode != 0:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
