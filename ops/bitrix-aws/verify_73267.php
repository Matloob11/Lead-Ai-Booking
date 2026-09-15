<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['REQUEST_URI'] = '/bitrix/tools/cli_probe.php';
$_SERVER['SCRIPT_FILENAME'] = '/home/bitrix/www/bitrix/tools/cli_probe.php';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
require_once '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';

$item = a7_owner_data_get_item(73267);
if (!$item) {
    echo "item_missing\n";
    exit(1);
}
$phones = a7_owner_data_collect_phones($item);
echo "title=" . ($item['title'] ?? '') . " cat=" . ($item['categoryId'] ?? '') . " phones=" . count($phones) . "\n";
foreach ($phones as $p) {
    echo $p['label'] . ' | ' . $p['field'] . ' | ' . $p['phone'] . "\n";
}

// telephony default line
$opts = [];
if (\Bitrix\Main\Loader::includeModule('voximplant')) {
    $opts['default_line'] = \COption::GetOptionString('voximplant', 'default_line', '');
}
echo "default_line=" . ($opts['default_line'] ?? '') . "\n";
