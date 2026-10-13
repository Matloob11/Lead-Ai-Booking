<?php
/**
 * A7 Share-idle alert — JSON for the popup (a7_share_idle.js).
 * Deployed to: /home/bitrix/www/bitrix/tools/a7_share_idle_api.php
 *
 *   ?action=pending              -> { ok, items: [{lead, title, by, hours, url}] }   (current user only)
 *   POST action=ack&lead=ID&how= -> { ok, acked }   how = open | dismiss   (sessid required)
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function a7si_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    die();
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7si_json(['ok' => false, 'error' => 'Unauthorized'], 401);
}
if (!class_exists('A7ShareIdle')) {
    $inc = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_share_idle.php';
    if (is_readable($inc)) {
        require_once $inc;
    }
}
if (!class_exists('A7ShareIdle')) {
    a7si_json(['ok' => false, 'error' => 'not installed'], 500);
}

$uid = (int) $USER->GetID();
$action = (string) ($_REQUEST['action'] ?? 'pending');

try {
    if ($action === 'pending') {
        a7si_json(['ok' => true, 'items' => A7ShareIdle::pending($uid)]);
    }
    if ($action === 'ack') {
        if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !check_bitrix_sessid()) {
            a7si_json(['ok' => false, 'error' => 'Bad request'], 400);
        }
        $how = in_array($_POST['how'] ?? '', ['open', 'dismiss'], true) ? $_POST['how'] : 'dismiss';
        a7si_json(['ok' => true, 'acked' => A7ShareIdle::ack($uid, max(0, (int) ($_POST['lead'] ?? 0)), $how)]);
    }
    a7si_json(['ok' => false, 'error' => 'Unknown action'], 400);
} catch (\Throwable $e) {
    A7ShareIdle::log('api error: ' . $e->getMessage());
    a7si_json(['ok' => false, 'error' => 'Server error'], 500);
}
