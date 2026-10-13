<?php

/**
 * One-time Bitrix local-application OAuth installation callback.
 *
 * This endpoint never calls 3CX and never creates CRM/telephony records.  Its
 * only mutation is an atomic, mode-0600 write of the renewable Bitrix app auth
 * payload after a private setup token is verified.
 */

const A7_TELEPHONY_APP_AUTH_FILE = '/var/lib/a7-3cx-worker/bitrix-app-auth.json';
const A7_TELEPHONY_APP_INSTALL_SECRET_FILE = '/etc/a7-3cx-worker/bitrix-app-install.secret';
const A7_TELEPHONY_APP_INSTALL_CONSUMED_FILE = '/var/lib/a7-3cx-worker/bitrix-app-install.consumed';

function a7_telephony_json(array $payload, int $status = 200): void
{
    while (ob_get_level() > 0) {
        ob_end_clean();
    }
    if (!headers_sent()) {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        header('X-Content-Type-Options: nosniff');
    }
    echo json_encode($payload, JSON_UNESCAPED_SLASHES);
    exit;
}

function a7_telephony_require_admin(): void
{
    if (!defined('NO_KEEP_STATISTIC')) {
        define('NO_KEEP_STATISTIC', true);
    }
    $documentRoot = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www'), '/');
    $prolog = $documentRoot . '/bitrix/modules/main/include/prolog_before.php';
    if (is_readable($prolog)) {
        require_once $prolog;
    }
    global $USER;
    if (!is_object($USER)
        || !method_exists($USER, 'IsAuthorized')
        || !$USER->IsAuthorized()
        || !method_exists($USER, 'IsAdmin')
        || !$USER->IsAdmin()
    ) {
        a7_telephony_json(['success' => false, 'message' => 'Bitrix admin login required'], 403);
    }
}

function a7_telephony_setup_secret(): string
{
    $path = A7_TELEPHONY_APP_INSTALL_SECRET_FILE;
    if (!is_readable($path)) {
        return '';
    }
    $secret = rtrim((string)file_get_contents($path), "\r\n");
    if (strlen($secret) < 32 || strlen($secret) > 4096) {
        return '';
    }
    return $secret;
}

function a7_telephony_valid_endpoint(string $endpoint): bool
{
    $parts = parse_url($endpoint);
    if (!is_array($parts) || strtolower((string)($parts['scheme'] ?? '')) !== 'https') {
        return false;
    }
    $endpointHost = strtolower((string)($parts['host'] ?? ''));
    $requestHost = strtolower(preg_replace('/:\d+$/', '', (string)($_SERVER['HTTP_HOST'] ?? '')) ?? '');
    return $endpointHost !== '' && $requestHost !== '' && hash_equals($requestHost, $endpointHost);
}

function a7_telephony_atomic_private_write(string $path, string $contents): bool
{
    $directory = dirname($path);
    if (!is_dir($directory) || !is_writable($directory)) {
        return false;
    }
    $temporary = tempnam($directory, '.bitrix-app-auth.');
    if (!is_string($temporary) || $temporary === '') {
        return false;
    }
    try {
        if (file_put_contents($temporary, $contents, LOCK_EX) === false) {
            return false;
        }
        if (!chmod($temporary, 0600) || !rename($temporary, $path)) {
            return false;
        }
        clearstatcache(true, $path);
        $mode = fileperms($path);
        return is_int($mode) && (($mode & 0777) === 0600);
    } finally {
        if (is_file($temporary)) {
            @unlink($temporary);
        }
    }
}

function a7_telephony_atomic_auth_write(array $payload): bool
{
    $encoded = json_encode($payload, JSON_UNESCAPED_SLASHES);
    return is_string($encoded)
        && a7_telephony_atomic_private_write(
            A7_TELEPHONY_APP_AUTH_FILE,
            $encoded . PHP_EOL
        );
}

function a7_telephony_install(): void
{
    if (strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET')) !== 'POST') {
        a7_telephony_json(['success' => false, 'message' => 'POST required'], 405);
    }
    if (is_file(A7_TELEPHONY_APP_AUTH_FILE)
        || is_file(A7_TELEPHONY_APP_INSTALL_CONSUMED_FILE)
    ) {
        a7_telephony_json([
            'success' => false,
            'message' => 'Install callback already consumed; explicit secure re-arm required',
        ], 409);
    }
    $expected = a7_telephony_setup_secret();
    $provided = (string)($_GET['setup'] ?? $_POST['setup'] ?? '');
    if ($expected === '' || $provided === '' || !hash_equals($expected, $provided)) {
        a7_telephony_json(['success' => false, 'message' => 'Invalid setup token'], 403);
    }
    $auth = $_POST['auth'] ?? [];
    if (!is_array($auth)) {
        a7_telephony_json(['success' => false, 'message' => 'Auth payload missing'], 400);
    }
    $accessToken = (string)($auth['access_token'] ?? '');
    $refreshToken = (string)($auth['refresh_token'] ?? '');
    $clientEndpoint = rtrim((string)($auth['client_endpoint'] ?? ''), '/');
    if (strlen($accessToken) < 16
        || strlen($accessToken) > 4096
        || strlen($refreshToken) < 16
        || strlen($refreshToken) > 4096
        || !a7_telephony_valid_endpoint($clientEndpoint)
    ) {
        a7_telephony_json(['success' => false, 'message' => 'Invalid auth payload'], 400);
    }
    $allowed = [];
    foreach ([
        'access_token', 'refresh_token', 'client_endpoint', 'domain',
        'member_id', 'expires_in', 'expires', 'scope', 'application_token',
    ] as $name) {
        if (array_key_exists($name, $auth) && !is_array($auth[$name]) && !is_object($auth[$name])) {
            $allowed[$name] = $auth[$name];
        }
    }
    $allowed['client_endpoint'] = $clientEndpoint;
    $allowed['installed_at'] = date('c');
    if (!a7_telephony_atomic_auth_write($allowed)) {
        a7_telephony_json(['success' => false, 'message' => 'Secure auth storage failed'], 500);
    }
    if (!a7_telephony_atomic_private_write(
        A7_TELEPHONY_APP_INSTALL_CONSUMED_FILE,
        date('c') . PHP_EOL
    )) {
        a7_telephony_json([
            'success' => false,
            'message' => 'Authorization stored but one-time callback lock failed',
        ], 500);
    }
    // This normally remains root-owned and therefore cannot be removed by PHP.
    // The consumed marker and existing auth file already prevent token reuse;
    // the operator must now remove the setup-secret file as a separate step.
    @unlink(A7_TELEPHONY_APP_INSTALL_SECRET_FILE);
    a7_telephony_json([
        'success' => true,
        'message' => 'A7 native telephony app authorization stored securely',
        'authFileConfigured' => true,
        'installCallbackConsumed' => true,
        'installSecretRemovalRequired' => is_readable(A7_TELEPHONY_APP_INSTALL_SECRET_FILE),
    ]);
}

$action = (string)($_GET['action'] ?? $_POST['action'] ?? '');
if ($action === 'install') {
    a7_telephony_install();
}
if ($action === 'status') {
    a7_telephony_require_admin();
    a7_telephony_json([
        'success' => true,
        'message' => 'A7 native telephony app callback is online',
        'authFileConfigured' => is_file(A7_TELEPHONY_APP_AUTH_FILE),
        'installSecretConfigured' => is_readable(A7_TELEPHONY_APP_INSTALL_SECRET_FILE),
        'installCallbackConsumed' => is_file(A7_TELEPHONY_APP_INSTALL_CONSUMED_FILE),
    ]);
}
a7_telephony_json([
    'success' => true,
    'message' => 'A7 native telephony app callback is online',
]);
