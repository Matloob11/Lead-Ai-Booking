<?php
/**
 * A7 phone-mask API (TL list + Admin & Finance auto-dept).
 * Actions: config | unlock
 *
 * Deploy to: /bitrix/tools/a7_tl_phone_mask.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_tl_phone_mask_lib.php';

header('Content-Type: application/json; charset=utf-8');

function a7_tl_mask_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES);
    exit;
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_tl_mask_json(['ok' => false, 'error' => 'Unauthorized'], 401);
}

$cfg = a7_tl_mask_config();
$leaders = isset($cfg['leaders']) && is_array($cfg['leaders']) ? $cfg['leaders'] : [];
$userId = (int)$USER->GetID();
$masked = a7_tl_mask_should_apply($userId, $cfg);
$reveal = (int)($cfg['reveal_seconds'] ?? 30);
if ($reveal < 5) {
    $reveal = 30;
}

$action = (string)($_REQUEST['action'] ?? 'config');

if ($action === 'config') {
    a7_tl_mask_json([
        'ok' => true,
        'isTl' => $masked,
        'masked' => $masked,
        'userId' => $userId,
        'revealSeconds' => $reveal,
        'team' => isset($leaders[$userId]) ? [
            'name' => (string)($leaders[$userId]['name'] ?? ''),
            'agents' => array_values(array_map('intval', $leaders[$userId]['agents'] ?? [])),
        ] : null,
    ]);
}

if ($action === 'unlock') {
    if (!$masked) {
        a7_tl_mask_json(['ok' => false, 'error' => 'Mask not enabled for this user'], 403);
    }
    $sessid = (string)($_REQUEST['sessid'] ?? '');
    if ($sessid === '' || !check_bitrix_sessid()) {
        a7_tl_mask_json(['ok' => false, 'error' => 'Invalid session'], 403);
    }
    $password = (string)($_REQUEST['password'] ?? '');
    $expected = (string)($cfg['password'] ?? '');
    if ($expected === '' || !hash_equals($expected, $password)) {
        a7_tl_mask_json(['ok' => false, 'error' => 'Wrong password'], 403);
    }
    if (!isset($_SESSION['A7_TL_PHONE_UNLOCK'])) {
        $_SESSION['A7_TL_PHONE_UNLOCK'] = [];
    }
    $_SESSION['A7_TL_PHONE_UNLOCK'][$userId] = time() + $reveal;
    a7_tl_mask_json([
        'ok' => true,
        'revealSeconds' => $reveal,
        'expiresAt' => (int)$_SESSION['A7_TL_PHONE_UNLOCK'][$userId],
    ]);
}

a7_tl_mask_json(['ok' => false, 'error' => 'Unknown action'], 400);
