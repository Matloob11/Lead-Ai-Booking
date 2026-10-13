<?php
define('NO_KEEP_STATISTIC', true);
define('NO_AGENT_STATISTIC', true);
define('NO_AGENT_CHECK', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
header('Content-Type: application/json; charset=UTF-8');
global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    echo '[]';
    return;
}
if (!defined('A7_LEAD_REMINDER_LIB')) {
    define('A7_LEAD_REMINDER_LIB', true);
}
$lib = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_lead_reminder_notify.php';
if (is_readable($lib)) {
    require_once $lib;
}
$items = function_exists('a7_lead_reminder_pending_for_user')
    ? a7_lead_reminder_pending_for_user((int)$USER->GetID())
    : [];
echo json_encode($items);
