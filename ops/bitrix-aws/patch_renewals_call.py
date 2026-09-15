#!/usr/bin/env python3
"""Add Renewals (deal cat 9) Voiso Call button: PHP phones action + JS inject."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PHP_PATH = Path("/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php")
INIT_PATH = Path("/home/bitrix/www/bitrix/php_interface/init.php")
JS_SRC = Path("/tmp/a7-od-call/a7_renewals_call.js")
JS_DST = Path("/home/bitrix/www/bitrix/js/a7_renewals_call.js")
MARKER = "A7_RENEWALS_CUSTOM_CALL"

HELPERS = r'''
/* === BEGIN ''' + MARKER + r''' HELPERS === */
function a7_renewals_deal_phone_fields(): array
{
    return [
        'UF_CRM_1734263575786' => 'Tenant phone',
        'UF_CRM_1735377605713' => 'Owner phone',
    ];
}

function a7_renewals_category_id(): int
{
    return 9;
}

function a7_deal_get(int $dealId): ?array
{
    if ($dealId <= 0) {
        return null;
    }
    $response = a7_bitrix_webhook_call('crm.deal.get', ['id' => $dealId]);
    $deal = $response['json']['result'] ?? null;
    if (!$response['ok'] || !is_array($deal)) {
        return null;
    }
    return $deal;
}

function a7_deal_collect_phones(array $deal): array
{
    $out = [];
    $seen = [];

    foreach (a7_renewals_deal_phone_fields() as $field => $label) {
        $value = $deal[$field] ?? null;
        $values = is_array($value) ? $value : [$value];
        foreach ($values as $candidate) {
            if ($candidate === null || trim((string)$candidate) === '' || trim((string)$candidate) === '0') {
                continue;
            }
            $phone = a7_clean_phone((string)$candidate);
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

    // Also include Contact PHONE if deal is linked (native path fields).
    $contactId = (int)($deal['CONTACT_ID'] ?? 0);
    if ($contactId > 0) {
        $contactResp = a7_bitrix_webhook_call('crm.contact.get', ['id' => $contactId]);
        $contact = $contactResp['json']['result'] ?? null;
        if ($contactResp['ok'] && is_array($contact)) {
            $phoneRows = $contact['PHONE'] ?? [];
            if (!is_array($phoneRows)) {
                $phoneRows = [];
            }
            foreach ($phoneRows as $row) {
                if (!is_array($row)) {
                    continue;
                }
                $raw = (string)($row['VALUE'] ?? '');
                $phone = a7_clean_phone($raw);
                $digits = preg_replace('/\D/', '', $phone) ?? '';
                if (strlen($digits) < 6) {
                    continue;
                }
                $key = strlen($digits) > 10 ? substr($digits, -10) : $digits;
                if (isset($seen[$key])) {
                    continue;
                }
                $seen[$key] = true;
                $type = (string)($row['VALUE_TYPE'] ?? 'WORK');
                $out[] = [
                    'phone' => $phone,
                    'label' => 'Contact phone (' . $type . ')',
                    'field' => 'CONTACT_PHONE',
                ];
            }
        }
    }

    return $out;
}

function a7_handle_deal_phones(): void
{
    a7_require_bitrix_user();
    $dealId = (int)a7_request_value('id', 0);
    if ($dealId <= 0) {
        a7_json(['success' => false, 'message' => 'Deal id missing'], 400);
    }

    $deal = a7_deal_get($dealId);
    if ($deal === null) {
        a7_json(['success' => false, 'message' => 'Deal not found'], 404);
    }

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
    a7_json([
        'success' => true,
        'skipped' => false,
        'dealId' => $dealId,
        'title' => (string)($deal['TITLE'] ?? ''),
        'categoryId' => $categoryId,
        'phones' => $phones,
        'count' => count($phones),
    ]);
}
/* === END ''' + MARKER + r''' HELPERS === */
'''

ROUTE = '''
    if ($action === 'deal-phones') {
        a7_handle_deal_phones();
    }
'''

INIT_BLOCK = r'''
// ''' + MARKER + r''': Renewals deals (category 9) custom Call button → Voiso.
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
        $scriptPath = '/bitrix/js/a7_renewals_call.js';
        $fullPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $scriptPath;
        $version = is_readable($fullPath) ? (string)@filemtime($fullPath) : (string)time();
        $APPLICATION->AddHeadScript($scriptPath . '?v=' . $version);
    });
}
'''


def backup(path: Path) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_suffix(path.suffix + f".bak.{stamp}")
    shutil.copy2(path, bak)
    print(f"backup {bak}")


def patch_php(text: str) -> str:
    if MARKER + " HELPERS" in text and "deal-phones" in text:
        print("php already patched")
        return text

    if MARKER + " HELPERS" not in text:
        needle = "/* === BEGIN A7_OWNER_DATA_CUSTOM_CALL HELPERS === */"
        if needle in text:
            text = text.replace(needle, HELPERS + "\n" + needle, 1)
        else:
            needle2 = "function a7_handle_owner_data_diagnostic(): void"
            if needle2 not in text:
                raise SystemExit("insert point not found")
            text = text.replace(needle2, HELPERS + "\n" + needle2, 1)

    if "deal-phones" not in text:
        od = "if ($action === 'owner-data-phones') {"
        if od in text:
            text = text.replace(od, ROUTE + "\n    " + od, 1)
        else:
            raise SystemExit("owner-data-phones route not found")

    return text


def patch_init(text: str) -> str:
    if MARKER in text:
        print("init already patched")
        return text
    return text.rstrip() + "\n" + INIT_BLOCK + "\n"


def main() -> int:
    if not JS_SRC.is_file():
        raise SystemExit(f"missing {JS_SRC}")
    backup(PHP_PATH)
    PHP_PATH.write_text(patch_php(PHP_PATH.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    print(f"patched {PHP_PATH}")
    backup(INIT_PATH)
    INIT_PATH.write_text(patch_init(INIT_PATH.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    print(f"patched {INIT_PATH}")
    shutil.copy2(JS_SRC, JS_DST)
    print(f"copied {JS_DST} ({JS_DST.stat().st_size} bytes)")
    for path in (PHP_PATH, INIT_PATH):
        r = subprocess.run(["php", "-l", str(path)], capture_output=True, text=True)
        print((r.stdout or r.stderr).strip())
        if r.returncode != 0:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
