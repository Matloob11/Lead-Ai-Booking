<?php
/**
 * CLI / cron entry — run every minute as user bitrix:
 *   * * * * * /usr/bin/php -f /home/bitrix/www/bitrix/php_interface/a7_auto_timeman_cron.php >/dev/null 2>&1
 *
 * Independent of page hits. Same logic as the Bitrix agent.
 */
if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "cli only\n");
    exit(1);
}

$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_auto_timeman_lib.php';

$result = a7_auto_tm_tick();
echo date('c') . ' ' . json_encode($result, JSON_UNESCAPED_SLASHES) . "\n";
