<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('STOP_STATISTICS', true);
define('NO_AGENT_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
if (!defined('A7_CI_LIB_ONLY')) {
    define('A7_CI_LIB_ONLY', true);
}
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_call_intelligence.php';
a7_call_intelligence_agent();
