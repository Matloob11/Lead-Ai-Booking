<?php
/**
 * C49: Lead AI escalation map — Bitrix user → team lead → department head.
 *
 * POST /bitrix/tools/a7_leadai_escalation.php
 * Headers: X-Leadai-Ts, X-Leadai-Sign = hex HMAC-SHA256(secret,
 *          "leadai-escalation." . ts . "." . body)
 * Body: {} or {"user_id": 123}
 * Answer: {"ok": true, "map": {"2311": {"lead": 2560, "head": 60}}}
 *   lead/head are user ids (0 when unknown). Built from company structure
 *   iblock 3: section UF_HEAD for the user's UF_DEPARTMENT, then parent UF_HEAD.
 *
 * Deploy to: /bitrix/tools/a7_leadai_escalation.php
 */

function a7_leadai_escalation_json(array $payload, int $code = 200): void
{
	http_response_code($code);
	header('Content-Type: application/json; charset=utf-8');
	echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
	exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
	a7_leadai_escalation_json(['ok' => false, 'error' => 'POST only.'], 405);
}
$cfgPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
$cfg = is_readable($cfgPath) ? include $cfgPath : null;
$secret = trim((string)((is_array($cfg) ? $cfg : [])['secret'] ?? ''));
if ($secret === '') {
	a7_leadai_escalation_json(['ok' => false, 'error' => 'Not configured.'], 503);
}
$raw = (string)file_get_contents('php://input');
if (strlen($raw) > 8192) {
	a7_leadai_escalation_json(['ok' => false, 'error' => 'Bad body.'], 400);
}
if ($raw === '') {
	$raw = '{}';
}
$ts = (string)($_SERVER['HTTP_X_LEADAI_TS'] ?? '');
$sign = strtolower((string)($_SERVER['HTTP_X_LEADAI_SIGN'] ?? ''));
if (!ctype_digit($ts) || abs(time() - (int)$ts) > 300 || !preg_match('/^[0-9a-f]{64}$/', $sign)) {
	a7_leadai_escalation_json(['ok' => false, 'error' => 'Unauthorized.'], 401);
}
if (!hash_equals(hash_hmac('sha256', 'leadai-escalation.' . $ts . '.' . $raw, $secret), $sign)) {
	a7_leadai_escalation_json(['ok' => false, 'error' => 'Unauthorized.'], 401);
}
$in = json_decode($raw, true);
if (!is_array($in)) {
	a7_leadai_escalation_json(['ok' => false, 'error' => 'Body is not JSON.'], 400);
}

define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

if (!\Bitrix\Main\Loader::includeModule('iblock')) {
	a7_leadai_escalation_json(['ok' => false, 'error' => 'iblock missing.'], 503);
}

const A7_ESCALATION_DEPT_IBLOCK = 3;

/** @return array<int, array{head:int, parent:int}> */
function a7_leadai_escalation_sections(): array
{
	static $cache = null;
	if ($cache !== null) {
		return $cache;
	}
	$cache = [];
	$rs = CIBlockSection::GetList(
		[],
		['IBLOCK_ID' => A7_ESCALATION_DEPT_IBLOCK, 'ACTIVE' => 'Y', 'CHECK_PERMISSIONS' => 'N'],
		false,
		['ID', 'IBLOCK_SECTION_ID', 'UF_HEAD']
	);
	while ($rs && ($row = $rs->Fetch())) {
		$cache[(int)$row['ID']] = [
			'head' => (int)($row['UF_HEAD'] ?? 0),
			'parent' => (int)($row['IBLOCK_SECTION_ID'] ?? 0),
		];
	}
	return $cache;
}

/**
 * @return array{lead:int, head:int}
 */
function a7_leadai_escalation_for(int $userId, array $deptIds, array $sections): array
{
	$lead = 0;
	$head = 0;
	foreach ($deptIds as $deptId) {
		$deptId = (int)$deptId;
		if ($deptId <= 0 || !isset($sections[$deptId])) {
			continue;
		}
		$sec = $sections[$deptId];
		$secHead = (int)$sec['head'];
		$parentId = (int)$sec['parent'];
		$parentHead = ($parentId > 0 && isset($sections[$parentId]))
			? (int)$sections[$parentId]['head']
			: 0;

		// Team lead = section head (or parent head if the user is the section head).
		if ($secHead > 0 && $secHead !== $userId) {
			$lead = $secHead;
		} elseif ($parentHead > 0 && $parentHead !== $userId) {
			$lead = $parentHead;
		}
		// Department head = parent section head (skip if same as lead).
		if ($parentHead > 0 && $parentHead !== $userId) {
			$head = $parentHead;
		} elseif ($parentId > 0 && isset($sections[$parentId])) {
			$gp = (int)$sections[$parentId]['parent'];
			if ($gp > 0 && isset($sections[$gp]) && (int)$sections[$gp]['head'] > 0) {
				$head = (int)$sections[$gp]['head'];
			}
		}
		if ($lead > 0 || $head > 0) {
			break;
		}
	}
	if ($head > 0 && $head === $lead) {
		// Prefer a distinct head one level up when both resolved to the same person.
		foreach ($deptIds as $deptId) {
			$deptId = (int)$deptId;
			if ($deptId <= 0 || !isset($sections[$deptId])) {
				continue;
			}
			$parentId = (int)$sections[$deptId]['parent'];
			if ($parentId <= 0 || !isset($sections[$parentId])) {
				continue;
			}
			$gp = (int)$sections[$parentId]['parent'];
			if ($gp > 0 && isset($sections[$gp])) {
				$gph = (int)$sections[$gp]['head'];
				if ($gph > 0 && $gph !== $lead && $gph !== $userId) {
					$head = $gph;
					break;
				}
			}
		}
	}
	return ['lead' => $lead, 'head' => $head];
}

$sections = a7_leadai_escalation_sections();
$only = (int)($in['user_id'] ?? 0);
$map = [];

$filter = ['ACTIVE' => 'Y'];
if ($only > 0) {
	$filter['ID'] = $only;
}
$rs = CUser::GetList(
	'id',
	'asc',
	$filter,
	['FIELDS' => ['ID'], 'SELECT' => ['UF_DEPARTMENT']]
);
while ($rs && ($row = $rs->Fetch())) {
	$uid = (int)$row['ID'];
	$depts = $row['UF_DEPARTMENT'] ?? [];
	if (!is_array($depts)) {
		$depts = $depts ? [(int)$depts] : [];
	}
	$depts = array_values(array_filter(array_map('intval', $depts)));
	if (!$depts) {
		continue;
	}
	$map[(string)$uid] = a7_leadai_escalation_for($uid, $depts, $sections);
}

a7_leadai_escalation_json([
	'ok' => true,
	'map' => $map,
	'count' => count($map),
	'scheme' => [
		'prefix' => 'leadai-escalation.',
		'headers' => ['X-Leadai-Ts', 'X-Leadai-Sign'],
		'url' => '/bitrix/tools/a7_leadai_escalation.php',
	],
]);
