<?php
/**
 * Register / refresh A7AutoTimemanAgent only (no stdout before Bitrix bootstrap).
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_auto_timeman_agent.php';

CAgent::RemoveAgent('A7AutoTimemanAgent::run();', '');
$id = CAgent::AddAgent(
    'A7AutoTimemanAgent::run();',
    '',
    'N',
    60,
    '',
    'Y',
    ConvertTimeStamp(time() + 60, 'FULL'),
    30,
    false,
    true
);

echo $id ? ("agent_id=$id\n") : "agent_add_failed\n";

$cronLine = '* * * * * /usr/bin/php -f /home/bitrix/www/bitrix/php_interface/a7_auto_timeman_cron.php >/dev/null 2>&1';
$cronFile = '/tmp/a7_auto_tm_cron_hint.txt';
file_put_contents($cronFile, $cronLine . "\n");
echo "cron_hint=$cronFile\n";
echo "DONE\n";
