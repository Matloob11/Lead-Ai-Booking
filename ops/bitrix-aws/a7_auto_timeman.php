<?php
/**
 * Matloob-only Auto Timeman toggle + status.
 * Deploy to: /bitrix/tools/a7_auto_timeman.php
 *
 * Actions: status | enable | disable | tick (admin self-test)
 * Refuses every caller except Bitrix user_id from config (2311).
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=utf-8');

$libDoc = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_auto_timeman_lib.php';
$libLocal = dirname(__DIR__) . '/php_interface/a7_auto_timeman_lib.php';
if (is_readable($libDoc)) {
    require_once $libDoc;
} elseif (is_readable(__DIR__ . '/a7_auto_timeman_lib.php')) {
    // When run from repo /tmp before copy — tools folder sibling not used on live.
    require_once __DIR__ . '/a7_auto_timeman_lib.php';
} else {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'lib_missing']);
    exit;
}

function a7_auto_tm_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_auto_tm_json(['ok' => false, 'error' => 'unauthorized'], 401);
}

$uid = (int)$USER->GetID();
if (!a7_auto_tm_is_target_user($uid)) {
    // Silent deny — no feature leak to other profiles.
    a7_auto_tm_json(['ok' => false, 'error' => 'forbidden'], 403);
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $sessid = (string)($_POST['sessid'] ?? $_REQUEST['sessid'] ?? '');
    if ($sessid === '' || !check_bitrix_sessid()) {
        a7_auto_tm_json(['ok' => false, 'error' => 'bad_sessid'], 403);
    }
}

$action = strtolower(trim((string)($_REQUEST['action'] ?? 'status')));
$cfg = a7_auto_tm_config();
$now = a7_auto_tm_now();
$status = a7_auto_tm_status($uid);

$base = [
    'ok' => true,
    'user_id' => $uid,
    'enabled' => a7_auto_tm_is_enabled(),
    'timezone' => (string)($cfg['timezone'] ?? 'Asia/Karachi'),
    'clock_in' => (string)($cfg['clock_in'] ?? '10:00'),
    'clock_out' => (string)($cfg['clock_out'] ?? '19:30'),
    'now' => $now->format('c'),
    'is_sunday' => a7_auto_tm_is_skip_day($now),
    'timeman_state' => $status['state'],
    'last_open' => a7_auto_tm_get_last('open'),
    'last_close' => a7_auto_tm_get_last('close'),
];

if ($action === 'status') {
    a7_auto_tm_json($base);
}

if ($action === 'enable') {
    a7_auto_tm_set_enabled(true);
    $base['enabled'] = true;
    $base['action'] = 'enable';
    a7_auto_tm_json($base);
}

if ($action === 'disable') {
    a7_auto_tm_set_enabled(false);
    $base['enabled'] = false;
    $base['action'] = 'disable';
    a7_auto_tm_json($base);
}

if ($action === 'tick') {
    $result = a7_auto_tm_tick();
    $base['tick'] = $result;
    $base['enabled'] = a7_auto_tm_is_enabled();
    $base['timeman_state'] = a7_auto_tm_status($uid)['state'];
    $base['last_open'] = a7_auto_tm_get_last('open');
    $base['last_close'] = a7_auto_tm_get_last('close');
    a7_auto_tm_json($base);
}

a7_auto_tm_json(['ok' => false, 'error' => 'unknown_action'], 400);
