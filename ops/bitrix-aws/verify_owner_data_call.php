<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['REQUEST_URI'] = '/bitrix/tools/cli_probe.php';
$_SERVER['SCRIPT_FILENAME'] = '/home/bitrix/www/bitrix/tools/cli_probe.php';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
require_once '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';

foreach ([88414, 88164, 88413] as $id) {
    $item = a7_owner_data_get_item($id);
    if (!$item) {
        echo "item={$id} missing\n";
        continue;
    }
    $phones = a7_owner_data_collect_phones($item);
    echo "item={$id} title=" . ($item['title'] ?? '') . " cat=" . ($item['categoryId'] ?? '') . " phones=" . count($phones) . "\n";
    foreach ($phones as $p) {
        echo "  " . $p['label'] . " | " . $p['field'] . " | " . $p['phone'] . "\n";
    }
}

echo "routes_ok=" . (function_exists('a7_handle_owner_data_phones') && function_exists('a7_handle_owner_data_call') ? '1' : '0') . "\n";
echo "js_ok=" . (is_readable('/home/bitrix/www/bitrix/js/a7_owner_data_call.js') ? '1' : '0') . "\n";
echo "init_ok=" . (strpos(file_get_contents('/home/bitrix/www/bitrix/php_interface/init.php'), 'a7_owner_data_call.js') !== false ? '1' : '0') . "\n";
