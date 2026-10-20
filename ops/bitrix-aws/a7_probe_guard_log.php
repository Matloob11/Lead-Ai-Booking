<?php
/**
 * Read-only probe: what A7 Lead Guard refused lately, and what it allows a shared user to change.
 * Prints the guard config (no secrets in it), the last BLOCK lines of its log, init.php's A7 wiring,
 * and A7LeadGuard::sharedAllowedFields(). Stub with _stub404.php after use (web-reachable directory).
 *
 * Run: ops/bitrix.sh run a7_probe_guard_log.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

function say(string $line): void
{
    echo $line, "\n";
}

$root = '/home/bitrix/www';
$cfgPath = $root . '/bitrix/php_interface/a7_lead_guard.config.php';
$cfg = is_readable($cfgPath) ? include $cfgPath : null;
say('config file: ' . (is_file($cfgPath) ? 'present' : 'MISSING'));
if (is_array($cfg)) {
    foreach ($cfg as $k => $v) {
        say('  ' . $k . ' = ' . json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
    }
}

$guard = $root . '/bitrix/php_interface/include/a7_lead_guard.php';
say('guard md5: ' . (is_file($guard) ? md5_file($guard) : 'MISSING'));
$perms = $root . '/bitrix/php_interface/include/a7_lead_guard_perms.php';
say('perms md5: ' . (is_file($perms) ? md5_file($perms) : 'MISSING'));
$init = (string) @file_get_contents($root . '/bitrix/php_interface/init.php');
foreach (explode("\n", $init) as $n => $line) {
    if (stripos($line, 'a7_') !== false || stripos($line, 'A7_') !== false) {
        say('init:' . ($n + 1) . ': ' . trim($line));
    }
}
$extra = (string) @file_get_contents($root . '/bitrix/.settings_extra.php');
say('settings_extra mentions A7CrmContainer: ' . (str_contains($extra, 'A7CrmContainer') ? 'yes' : 'NO'));

$log = is_array($cfg) ? (string) ($cfg['log_file'] ?? '') : '';
if ($log !== '' && is_readable($log)) {
    say('log: ' . $log . ' (' . filesize($log) . ' bytes)');
    $lines = file($log, FILE_IGNORE_NEW_LINES) ?: [];
    $blocks = array_values(array_filter($lines, static fn($l) => str_contains($l, 'BLOCK') || str_contains($l, 'error')));
    say('BLOCK/error lines: ' . count($blocks) . ' of ' . count($lines));
    foreach (array_slice($blocks, -60) as $l) {
        say('  ' . $l);
    }
} else {
    say('log: none readable (' . $log . ')');
}

if (\Bitrix\Main\Loader::includeModule('crm')) {
    require_once $guard;
    say('guard version: ' . A7LeadGuard::VERSION);
    $allowed = A7LeadGuard::sharedAllowedFields();
    ksort($allowed);
    say('sharedAllowedFields: ' . implode(', ', array_keys($allowed)));
}
say('DONE');
