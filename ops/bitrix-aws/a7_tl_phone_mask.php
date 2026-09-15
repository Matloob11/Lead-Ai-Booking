<?php
/**
 * A7 Team Lead phone-mask API.
 * Actions: config | unlock
 *
 * Deploy to: /bitrix/tools/a7_tl_phone_mask.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=utf-8');

function a7_tl_mask_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES);
    exit;
}

function a7_tl_mask_config(): array
{
    $path = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_tl_phone_mask.config.php';
    if (!is_readable($path)) {
        $path = __DIR__ . '/a7_tl_phone_mask.config.php';
    }
    $cfg = is_readable($path) ? include $path : null;
    return is_array($cfg) ? $cfg : [];
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_tl_mask_json(['ok' => false, 'error' => 'Unauthorized'], 401);
}

$cfg = a7_tl_mask_config();
$leaders = isset($cfg['leaders']) && is_array($cfg['leaders']) ? $cfg['leaders'] : [];
$userId = (int) $USER->GetID();
$isTl = isset($leaders[$userId]);
$reveal = (int) ($cfg['reveal_seconds'] ?? 30);
if ($reveal < 5) {
    $reveal = 30;
}

$action = (string) ($_REQUEST['action'] ?? 'config');

if ($action === 'config') {
    a7_tl_mask_json([
        'ok' => true,
        'isTl' => $isTl,
        'userId' => $userId,
        'revealSeconds' => $reveal,
        'team' => $isTl ? [
            'name' => (string) ($leaders[$userId]['name'] ?? ''),
            'agents' => array_values(array_map('intval', $leaders[$userId]['agents'] ?? [])),
        ] : null,
    ]);
}

if ($action === 'unlock') {
    if (!$isTl) {
        a7_tl_mask_json(['ok' => false, 'error' => 'Not a team lead'], 403);
    }
    $sessid = (string) ($_REQUEST['sessid'] ?? '');
    if ($sessid === '' || !check_bitrix_sessid()) {
        a7_tl_mask_json(['ok' => false, 'error' => 'Invalid session'], 403);
    }
    $password = (string) ($_REQUEST['password'] ?? '');
    $expected = (string) ($cfg['password'] ?? 'admin222007');
    if (!hash_equals($expected, $password)) {
        a7_tl_mask_json(['ok' => false, 'error' => 'Wrong password'], 403);
    }
    if (!isset($_SESSION['A7_TL_PHONE_UNLOCK'])) {
        $_SESSION['A7_TL_PHONE_UNLOCK'] = [];
    }
    $_SESSION['A7_TL_PHONE_UNLOCK'][$userId] = time() + $reveal;
    a7_tl_mask_json([
        'ok' => true,
        'revealSeconds' => $reveal,
        'expiresAt' => (int) $_SESSION['A7_TL_PHONE_UNLOCK'][$userId],
    ]);
}

a7_tl_mask_json(['ok' => false, 'error' => 'Unknown action'], 400);
