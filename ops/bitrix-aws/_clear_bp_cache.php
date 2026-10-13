<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_CRONTAB', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

if (function_exists('BXClearCache')) {
    BXClearCache(true);
}
$app = \Bitrix\Main\Application::getInstance();
if (method_exists($app->getManagedCache(), 'cleanAll')) {
    $app->getManagedCache()->cleanAll();
}
echo "CACHE_CLEARED\n";
