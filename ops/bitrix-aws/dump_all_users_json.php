#!/usr/bin/env php
<?php
/**
 * Dump Bitrix users for bitrix-all-users.html.
 * Default: ACTIVE employees only (no bots / empty EXTERNAL_AUTH_ID).
 * Pass --all to include inactive.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

CModule::IncludeModule('main');

$includeInactive = in_array('--all', $argv ?? [], true);

$by = 'ID';
$order = 'ASC';
$filter = $includeInactive ? [] : ['ACTIVE' => 'Y'];
$params = [
	'FIELDS' => [
		'ID', 'NAME', 'LAST_NAME', 'EMAIL', 'ACTIVE', 'WORK_POSITION',
		'LOGIN', 'EXTERNAL_AUTH_ID',
	],
];

$rs = CUser::GetList($by, $order, $filter, $params);
$out = [];
$skipped = ['bot' => 0, 'external' => 0];
while ($u = $rs->Fetch()) {
	$ext = trim((string)($u['EXTERNAL_AUTH_ID'] ?? ''));
	// Skip Bitrix bots / imbot / email-auth ghosts unless --all
	if (!$includeInactive) {
		if ($ext !== '' && $ext !== 'socservices') {
			$skipped['external']++;
			continue;
		}
		$login = strtolower((string)($u['LOGIN'] ?? ''));
		$name = strtolower(trim((string)($u['NAME'] ?? '') . ' ' . (string)($u['LAST_NAME'] ?? '')));
		if (
			str_contains($login, 'bot')
			|| str_contains($name, 'copilot')
			|| str_contains($name, 'bitrix24 support')
			|| $name === 'guest'
			|| $login === 'guest'
		) {
			$skipped['bot']++;
			continue;
		}
	}

	$name = trim(trim((string)($u['NAME'] ?? '')) . ' ' . trim((string)($u['LAST_NAME'] ?? '')));
	if ($name === '') {
		$name = (string)($u['EMAIL'] ?: $u['LOGIN'] ?: $u['ID']);
	}
	$out[] = [
		'id' => (int)$u['ID'],
		'name' => $name,
		'email' => (string)($u['EMAIL'] ?? ''),
		'active' => ((string)($u['ACTIVE'] ?? '') === 'Y'),
		'work_position' => (string)($u['WORK_POSITION'] ?? ''),
		'external_auth_id' => $ext,
	];
}

usort($out, static fn($a, $b) => $a['id'] <=> $b['id']);

// Strip helper fields from public dump
$public = array_map(static function ($r) {
	return [
		'id' => $r['id'],
		'name' => $r['name'],
		'email' => $r['email'],
		'active' => $r['active'],
		'work_position' => $r['work_position'],
	];
}, $out);

fwrite(STDERR, 'count=' . count($public) . ' skipped_bot=' . $skipped['bot'] . ' skipped_ext=' . $skipped['external'] . "\n");
echo json_encode($public, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
echo "\n";
