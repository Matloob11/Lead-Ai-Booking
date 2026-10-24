<?php
/**
 * Commission Zone is a dropdown: International City, Outside International City.
 * CLI only. Keeps the same field name and id.
 */
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
	http_response_code(404);
	exit;
}

$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
define('A7_PORTAL_LEAD_FIELDS_BYPASS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

\Bitrix\Main\Loader::includeModule('crm');

$conn = \Bitrix\Main\Application::getConnection();
$sql = $conn->getSqlHelper();
global $APPLICATION;

function say(string $line): void
{
	echo $line, "\n";
}

$name = 'UF_CRM_A7_COMMISSION_ZONE';
$safe = $sql->forSql($name);
$row = $conn->query(
	"SELECT ID, USER_TYPE_ID FROM b_user_field WHERE ENTITY_ID='CRM_LEAD' AND FIELD_NAME='{$safe}'"
)->fetch();
if (!is_array($row)) {
	say('MISSING ' . $name);
	exit(1);
}
$fieldId = (int)$row['ID'];
say("field {$name} id={$fieldId} type={$row['USER_TYPE_ID']}");

$filled = 0;
$col = $conn->query("SHOW COLUMNS FROM b_uts_crm_lead LIKE '{$safe}'")->fetch();
if (is_array($col)) {
	$filled = (int)$conn->query(
		"SELECT COUNT(*) C FROM b_uts_crm_lead WHERE {$name} IS NOT NULL AND {$name}<>'' AND {$name}<>'0'"
	)->fetch()['C'];
}
say("filled={$filled}");
if ($filled > 0 && (string)$row['USER_TYPE_ID'] === 'string') {
	say('REFUSING: zone already has text on leads');
	exit(1);
}

if ((string)$row['USER_TYPE_ID'] !== 'enumeration') {
	if (is_object($APPLICATION) && method_exists($APPLICATION, 'ResetException')) {
		$APPLICATION->ResetException();
	}
	$entity = new CUserTypeEntity();
	$ok = $entity->Update($fieldId, [
		'USER_TYPE_ID' => 'enumeration',
		'SETTINGS' => [
			'DISPLAY' => 'LIST',
			'LIST_HEIGHT' => 1,
			'CAPTION_NO_VALUE' => '',
			'SHOW_NO_VALUE' => 'Y',
		],
	]);
	if (!$ok) {
		$ex = is_object($APPLICATION) ? $APPLICATION->GetException() : null;
		say('UPDATE FAILED: ' . ($ex ? $ex->GetString() : '?'));
		exit(1);
	}
	say('type is now enumeration');
}

$have = [];
$rs = $conn->query("SELECT ID, VALUE, SORT FROM b_user_field_enum WHERE USER_FIELD_ID={$fieldId} ORDER BY SORT, ID");
while ($rs && ($enum = $rs->fetch())) {
	$have[trim((string)$enum['VALUE'])] = ['id' => (int)$enum['ID'], 'sort' => (int)$enum['SORT']];
}
$wanted = ['International City' => 100, 'Outside International City' => 200];
$lower = [];
foreach ($have as $value => $meta) {
	$lower[strtolower($value)] = $value;
}
$missing = [];
foreach ($wanted as $value => $sort) {
	if (!isset($lower[strtolower($value)])) {
		$missing[$value] = $sort;
	}
}
if ($missing) {
	$payload = [];
	foreach ($have as $value => $meta) {
		$payload[$meta['id']] = ['ID' => $meta['id'], 'VALUE' => $value, 'SORT' => $meta['sort'], 'DEF' => 'N'];
	}
	$i = 0;
	foreach ($missing as $value => $sort) {
		$payload['n' . $i] = ['VALUE' => $value, 'SORT' => $sort, 'DEF' => 'N'];
		$i++;
	}
	$enum = new CUserFieldEnum();
	if (!$enum->SetEnumValues($fieldId, $payload)) {
		say('SetEnumValues FAILED');
		exit(1);
	}
	say('added: ' . implode(', ', array_keys($missing)));
}

$check = $conn->query(
	"SELECT USER_TYPE_ID FROM b_user_field WHERE ID={$fieldId}"
)->fetch();
say('type_now=' . $check['USER_TYPE_ID']);
$rs = $conn->query("SELECT ID, VALUE FROM b_user_field_enum WHERE USER_FIELD_ID={$fieldId} ORDER BY SORT, ID");
while ($rs && ($enum = $rs->fetch())) {
	say($enum['VALUE'] . '=' . $enum['ID']);
}
say('DONE');
