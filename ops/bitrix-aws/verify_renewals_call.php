<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['REQUEST_URI'] = '/bitrix/tools/cli_probe.php';
$_SERVER['SCRIPT_FILENAME'] = '/home/bitrix/www/bitrix/tools/cli_probe.php';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
require_once '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';

foreach ([35117, 39064] as $id) {
    $deal = a7_deal_get($id);
    if (!$deal) {
        echo "deal={$id} missing\n";
        continue;
    }
    $phones = a7_deal_collect_phones($deal);
    echo "deal={$id} cat=" . ($deal['CATEGORY_ID'] ?? '') . " title=" . ($deal['TITLE'] ?? '') . " phones=" . count($phones) . "\n";
    foreach ($phones as $p) {
        echo "  " . $p['label'] . " | " . $p['phone'] . "\n";
    }
}
echo "fn_ok=" . (function_exists('a7_handle_deal_phones') ? '1' : '0') . "\n";
echo "js_ok=" . (is_readable('/home/bitrix/www/bitrix/js/a7_renewals_call.js') ? '1' : '0') . "\n";
echo "init_ok=" . (strpos(file_get_contents('/home/bitrix/www/bitrix/php_interface/init.php'), 'a7_renewals_call.js') !== false ? '1' : '0') . "\n";
