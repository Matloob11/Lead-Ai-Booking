#!/usr/bin/env python3
"""Patch Bitrix AWS files for Owner Data custom Call button."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

ROOT = Path("/home/bitrix/www")
PHP = ROOT / "bitrix/tools/a7_3cx_click_to_call.php"
INIT = ROOT / "bitrix/php_interface/init.php"
JS_DST = ROOT / "bitrix/js/a7_owner_data_call.js"
HANDLERS_DST = ROOT / "bitrix/tools/a7_owner_data_call_handlers.php"
SRC = Path("/tmp/a7-od-call")
JS_SRC = SRC / "a7_owner_data_call.js"
HANDLERS_SRC = SRC / "a7_owner_data_call_handlers.php"

stamp = time.strftime("%Y%m%dT%H%M%SZ")


def backup(path: Path) -> None:
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak.{stamp}"))


def main() -> None:
    if not JS_SRC.is_file() or not HANDLERS_SRC.is_file():
        raise SystemExit(f"missing sources in {SRC}")
    if not PHP.is_file() or not INIT.is_file():
        raise SystemExit("missing Bitrix PHP targets")

    backup(PHP)
    backup(INIT)

    shutil.copy2(JS_SRC, JS_DST)
    shutil.copy2(HANDLERS_SRC, HANDLERS_DST)
    JS_DST.chmod(0o644)
    HANDLERS_DST.chmod(0o644)

    php = PHP.read_text(encoding="utf-8", errors="replace")

    # Widen Owner Data phone field map used by recording match + diagnostic.
    old_fields = """function a7_owner_data_phone_fields(): array
{
    return [
        'ufCrm5_1768317611513' => 'phone number',
        'ufCrm5_1768314841508' => 'Import Owner Mobile',
        'ufCrm5_1768317656051' => 'mobile number 2',
        'ufCrm5_1769416533028' => 'phone number 1',
    ];
}"""
    new_fields = """function a7_owner_data_phone_fields(): array
{
    return [
        'ufCrm5_1768317611513' => 'phone number',
        'ufCrm5_1769416533028' => 'phone number 1',
        'ufCrm5_1768314841508' => 'Import Owner Mobile',
        'ufCrm5_1768317656051' => 'mobile number 2',
        'ufCrm5_1777563197150' => 'Owner no 1',
        'ufCrm5_1779805546251' => 'Owner phone extra',
    ];
}"""
    if old_fields in php:
        php = php.replace(old_fields, new_fields, 1)
    elif "ufCrm5_1777563197150" not in php:
        raise SystemExit("could not patch a7_owner_data_phone_fields")

    require_line = "require_once __DIR__ . '/a7_owner_data_call_handlers.php';\n"
    if "a7_owner_data_call_handlers.php" not in php:
        anchor = "function a7_route_request(): void\n{"
        if anchor not in php:
            raise SystemExit("route anchor missing")
        php = php.replace(anchor, require_line + "\n" + anchor, 1)

    route_snip = """    if ($action === 'owner-data-phones') {
        a7_handle_owner_data_phones();
    }

    if ($action === 'owner-data-call') {
        a7_handle_owner_data_call();
    }

"""
    if "owner-data-phones" not in php:
        needle = "    if ($action === 'owner-data-diagnostic') {\n        a7_handle_owner_data_diagnostic();\n    }\n"
        if needle not in php:
            raise SystemExit("diagnostic route missing")
        php = php.replace(needle, needle + "\n" + route_snip, 1)

    # Diagnostic was category-14 only; allow any Owner Data item.
    php = php.replace(
        "if (!$response['ok'] || !is_array($item) || (int)($item['categoryId'] ?? 0) !== A7_OWNER_DATA_CATEGORY_ID) {\n"
        "        a7_json(['success' => false, 'message' => 'Owner Data item not found in category 14'], 404);\n"
        "    }",
        "if (!$response['ok'] || !is_array($item)) {\n"
        "        a7_json(['success' => false, 'message' => 'Owner Data item not found'], 404);\n"
        "    }",
        1,
    )

    PHP.write_text(php, encoding="utf-8")

    init = INIT.read_text(encoding="utf-8", errors="replace")
    if "a7_owner_data_call.js" not in init:
        block = """
// A7 Owner Data custom Call button (SPA 1042 only).
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
"""
        init = init.rstrip() + "\n" + block + "\n"
        INIT.write_text(init, encoding="utf-8")

    print("patched ok")
    print("js", JS_DST, "mtime", int(JS_DST.stat().st_mtime))
    print("handlers", HANDLERS_DST)
    print("php has routes", "owner-data-phones" in PHP.read_text(encoding="utf-8"))
    print("init has js", "a7_owner_data_call.js" in INIT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
