<?php
/**
 * Minute cron / nohup worker for background team-assign jobs.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
define('A7_TEAM_ASSIGN_AS_LIB', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/tools/a7_team_assign.php';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_team_assign_jobs.php';

$lock = '/tmp/a7_team_assign_worker.lock';
$fp = fopen($lock, 'c+');
if (!$fp || !flock($fp, LOCK_EX | LOCK_NB)) {
    echo "busy\n";
    exit(0);
}

$cfg = a7_ta_config();
@set_time_limit(120);
$result = a7_ta_job_run_worker($cfg, 55);
echo json_encode($result, JSON_UNESCAPED_SLASHES) . "\n";

flock($fp, LOCK_UN);
fclose($fp);
