<?php
/**
 * Create the five Booking-only lead fields and hide them on every other stage.
 * CLI only. Idempotent.
 *
 * Run: ops/bitrix.sh run a7_booking_fields_setup.php
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

function labels(string $text): array
{
	$out = [];
	foreach (['en', 'br', 'fr', 'it', 'la', 'pl', 'ua'] as $lang) {
		$out[$lang] = $text;
	}
	return $out;
}

function fieldRow(string $name): ?array
{
	global $conn, $sql;
	$safe = $sql->forSql($name);
	$row = $conn->query(
		"SELECT ID, USER_TYPE_ID FROM b_user_field WHERE ENTITY_ID='CRM_LEAD' AND FIELD_NAME='{$safe}'"
	)->fetch();
	return is_array($row) ? $row : null;
}

function enumMap(int $fieldId): array
{
	global $conn;
	$out = [];
	$rs = $conn->query(
		"SELECT ID, VALUE, SORT FROM b_user_field_enum WHERE USER_FIELD_ID={$fieldId} ORDER BY SORT, ID"
	);
	while ($rs && ($row = $rs->fetch())) {
		$out[trim((string)$row['VALUE'])] = ['id' => (int)$row['ID'], 'sort' => (int)$row['SORT']];
	}
	return $out;
}

function ensureField(string $name, string $type, string $label, string $xmlId, array $settings): int
{
	global $APPLICATION;
	$existing = fieldRow($name);
	if ($existing) {
		say("field {$name} exists id={$existing['ID']} type={$existing['USER_TYPE_ID']}");
		return (int)$existing['ID'];
	}
	if (is_object($APPLICATION) && method_exists($APPLICATION, 'ResetException')) {
		$APPLICATION->ResetException();
	}
	$entity = new CUserTypeEntity();
	$id = (int)$entity->Add([
		'ENTITY_ID' => 'CRM_LEAD',
		'FIELD_NAME' => $name,
		'USER_TYPE_ID' => $type,
		'XML_ID' => $xmlId,
		'SORT' => 910,
		'MULTIPLE' => 'N',
		'MANDATORY' => 'N',
		'SHOW_FILTER' => 'N',
		'SHOW_IN_LIST' => 'N',
		'EDIT_IN_LIST' => 'Y',
		'IS_SEARCHABLE' => 'N',
		'SETTINGS' => $settings,
		'EDIT_FORM_LABEL' => labels($label),
		'LIST_COLUMN_LABEL' => labels($label),
		'LIST_FILTER_LABEL' => labels($label),
		'ERROR_MESSAGE' => labels(''),
		'HELP_MESSAGE' => labels(''),
	]);
	if ($id <= 0) {
		$ex = is_object($APPLICATION) ? $APPLICATION->GetException() : null;
		say('CREATE FAILED ' . $name . ': ' . ($ex ? $ex->GetString() : '?'));
		exit(1);
	}
	say("field {$name} created id={$id} type={$type}");
	return $id;
}

function ensureEnums(int $fieldId, array $wanted): void
{
	$have = enumMap($fieldId);
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
	if (!$missing) {
		return;
	}
	$payload = [];
	foreach ($have as $value => $meta) {
		$payload[$meta['id']] = [
			'ID' => $meta['id'],
			'VALUE' => $value,
			'SORT' => $meta['sort'],
			'DEF' => 'N',
		];
	}
	$i = 0;
	foreach ($missing as $value => $sort) {
		$payload['n' . $i] = ['VALUE' => $value, 'SORT' => $sort, 'DEF' => 'N'];
		$i++;
	}
	$enum = new CUserFieldEnum();
	if (!$enum->SetEnumValues($fieldId, $payload)) {
		say("SetEnumValues FAILED for field {$fieldId}");
		exit(1);
	}
	say('added enums on ' . $fieldId . ': ' . implode(', ', array_keys($missing)));
}

function collectNames($node, array &$names): void
{
	if (!is_array($node)) {
		return;
	}
	if (isset($node['name']) && is_string($node['name'])) {
		$names[$node['name']] = true;
	}
	foreach ($node as $child) {
		if (is_array($child)) {
			collectNames($child, $names);
		}
	}
}

function appendBooking($cfg, array $fieldNames): array
{
	if (!is_array($cfg)) {
		return $cfg;
	}
	$names = [];
	collectNames($cfg, $names);
	if (isset($names['a7_booking_fields'])) {
		return $cfg;
	}
	$add = [];
	foreach ($fieldNames as $name) {
		if (!isset($names[$name])) {
			$add[] = ['name' => $name, 'optionFlags' => '1'];
		}
	}
	if (!$add) {
		return $cfg;
	}
	$section = [
		'name' => 'a7_booking_fields',
		'title' => 'Booking',
		'type' => 'section',
		'elements' => $add,
	];
	if (isset($cfg[0]['elements']) && is_array($cfg[0]['elements'])) {
		$cfg[0]['elements'][] = $section;
		return $cfg;
	}
	$cfg[] = $section;
	return $cfg;
}

$enumSettings = [
	'DISPLAY' => 'LIST',
	'LIST_HEIGHT' => 1,
	'CAPTION_NO_VALUE' => '',
	'SHOW_NO_VALUE' => 'Y',
];
$stringSettings = [
	'SIZE' => 40,
	'ROWS' => 1,
	'REGEXP' => '',
	'MIN_LENGTH' => 0,
	'MAX_LENGTH' => 0,
	'DEFAULT_VALUE' => '',
];
$fileSettings = [
	'SIZE' => 20,
	'LIST_WIDTH' => 0,
	'LIST_HEIGHT' => 0,
	'MAX_SHOW_SIZE' => 0,
	'MAX_ALLOWED_SIZE' => 0,
	'EXTENSIONS' => [],
];

$fields = [
	'UF_CRM_A7_BOOKING_RENT_SALE',
	'UF_CRM_A7_COMMISSION_ZONE',
	'UF_CRM_A7_COMMISSION_DOC',
	'UF_CRM_A7_COMMISSION_STATUS',
	'UF_CRM_A7_COMMISSION_VOUCHER',
];

$rent = ensureField('UF_CRM_A7_BOOKING_RENT_SALE', 'enumeration', 'Rent or Sale', 'A7_BOOKING_RENT_SALE', $enumSettings);
ensureEnums($rent, ['Rent' => 100, 'Sale' => 200]);
$zone = ensureField('UF_CRM_A7_COMMISSION_ZONE', 'enumeration', 'Commission Zone', 'A7_COMMISSION_ZONE', $enumSettings);
ensureEnums($zone, ['International City' => 100, 'Outside International City' => 200]);
ensureField('UF_CRM_A7_COMMISSION_DOC', 'file', 'Commission Document', 'A7_COMMISSION_DOC', $fileSettings);
$status = ensureField('UF_CRM_A7_COMMISSION_STATUS', 'enumeration', 'Commission Status', 'A7_COMMISSION_STATUS', $enumSettings);
ensureEnums($status, ['Pending' => 100, 'Approved' => 200, 'Paid' => 300]);
ensureField('UF_CRM_A7_COMMISSION_VOUCHER', 'string', 'Commission Voucher No', 'A7_COMMISSION_VOUCHER', $stringSettings);

$bookingSort = (int)$conn->query(
	"SELECT SORT FROM b_crm_status WHERE ENTITY_ID='STATUS' AND STATUS_ID='CONVERTED'"
)->fetch()['SORT'];
$before = (string)$conn->query(
	"SELECT STATUS_ID FROM b_crm_status WHERE ENTITY_ID='STATUS' AND SORT < {$bookingSort} ORDER BY SORT DESC, ID DESC LIMIT 1"
)->fetch()['STATUS_ID'];
$afterRow = $conn->query(
	"SELECT STATUS_ID FROM b_crm_status WHERE ENTITY_ID='STATUS' AND SORT > {$bookingSort} ORDER BY SORT ASC, ID ASC LIMIT 1"
)->fetch();
$last = (string)$conn->query(
	"SELECT STATUS_ID FROM b_crm_status WHERE ENTITY_ID='STATUS' ORDER BY SORT DESC, ID DESC LIMIT 1"
)->fetch()['STATUS_ID'];
$after = is_array($afterRow) ? (string)$afterRow['STATUS_ID'] : '';
say("hide before {$before} and after {$after} through {$last}; booking sort {$bookingSort}");

$scopes = [''];
$scopeRs = $conn->query("SELECT DISTINCT ENTITY_SCOPE FROM b_crm_field_attr WHERE ENTITY_TYPE_ID=1");
while ($scopeRs && ($scopeRow = $scopeRs->fetch())) {
	$scope = (string)$scopeRow['ENTITY_SCOPE'];
	if (!in_array($scope, $scopes, true)) {
		$scopes[] = $scope;
	}
}

$attrSource = file_get_contents('/home/bitrix/www/bitrix/modules/crm/lib/attribute/entity/fieldattribute.php');
$attrNs = '';
$attrShort = '';
if (preg_match('/namespace\s+([^;]+);/', (string)$attrSource, $nsMatch)) {
	$attrNs = trim($nsMatch[1]);
}
if (preg_match('/class\s+(\w+)/', (string)$attrSource, $classMatch)) {
	$attrShort = trim($classMatch[1]);
}
$attrClass = $attrNs !== '' && $attrShort !== '' ? $attrNs . '\\' . $attrShort : '';
if ($attrClass === '' || !class_exists($attrClass)) {
	say('field attribute class missing: ' . $attrClass);
	exit(1);
}
say('attr class ' . $attrClass);
$ranges = [['NEW', $before, 2]];
if ($after !== '' && $after !== 'CONVERTED') {
	$ranges[] = [$after, $last, 2];
	$ranges[] = [$after, $last, 3];
}
foreach ($fields as $name) {
	$existing = $attrClass::getList([
		'filter' => ['=ENTITY_TYPE_ID' => 1, '=TYPE_ID' => 1, '=FIELD_NAME' => $name],
		'select' => ['ID'],
	]);
	while ($row = $existing->fetch()) {
		$attrClass::delete((int)$row['ID']);
	}
	foreach ($scopes as $scope) {
		foreach ($ranges as [$start, $finish, $group]) {
			$add = $attrClass::add([
				'ENTITY_TYPE_ID' => 1,
				'ENTITY_SCOPE' => $scope,
				'TYPE_ID' => 1,
				'FIELD_NAME' => $name,
				'CREATED_TIME' => new \Bitrix\Main\Type\DateTime(),
				'START_PHASE' => $start,
				'FINISH_PHASE' => $finish,
				'PHASE_GROUP_TYPE_ID' => $group,
				'IS_CUSTOM_FIELD' => 'Y',
			]);
			if (!$add->isSuccess()) {
				say('ATTR FAILED ' . $name . ' ' . implode('; ', $add->getErrorMessages()));
				exit(1);
			}
		}
	}
	say("hidden {$name} on every stage except Booking");
}

$backup = '/home/bitrix/a7_booking_fields_bak_' . date('Ymd_His');
if (!mkdir($backup, 0755, true) && !is_dir($backup)) {
	say('backup dir failed');
	exit(1);
}

$formRows = $conn->query(
	"SELECT ID, USER_ID, NAME, VALUE FROM b_user_option
	 WHERE CATEGORY='crm.entity.editor' AND NAME IN ('lead_details','lead_details_common')"
);
while ($formRows && ($row = $formRows->fetch())) {
	file_put_contents($backup . '/option_' . (int)$row['ID'] . '.ser', (string)$row['VALUE']);
	$cfg = @unserialize((string)$row['VALUE'], ['allowed_classes' => false]);
	if (!is_array($cfg)) {
		say('form option ' . $row['ID'] . ' did not unserialize');
		continue;
	}
	$next = appendBooking($cfg, $fields);
	$common = ((string)$row['NAME'] === 'lead_details_common');
	\CUserOptions::SetOption('crm.entity.editor', (string)$row['NAME'], $next, $common, (int)$row['USER_ID']);
	say('form ' . $row['NAME'] . ' user=' . $row['USER_ID']);
}

$configs = $conn->query("SELECT ID, NAME, CONFIG FROM b_ui_entity_editor_config WHERE ENTITY_TYPE_ID='lead_details'");
while ($configs && ($row = $configs->fetch())) {
	file_put_contents($backup . '/editor_' . (int)$row['ID'] . '.ser', (string)$row['CONFIG']);
	$cfg = @unserialize((string)$row['CONFIG'], ['allowed_classes' => false]);
	if (!is_array($cfg)) {
		say('editor config ' . $row['ID'] . ' did not unserialize');
		continue;
	}
	$next = appendBooking($cfg, $fields);
	$packed = $sql->forSql(serialize($next));
	$conn->queryExecute("UPDATE b_ui_entity_editor_config SET CONFIG='{$packed}' WHERE ID=" . (int)$row['ID']);
	say('editor config ' . $row['ID'] . ' ' . $row['NAME']);
}

function addKanban(array $cfg, array $names): array
{
	foreach ($names as $name) {
		if (!array_key_exists($name, $cfg)) {
			$cfg[$name] = '';
		}
	}
	return $cfg;
}

$kanbanRows = $conn->query(
	"SELECT ID, USER_ID, NAME, COMMON, VALUE FROM b_user_option
	 WHERE CATEGORY='crm' AND NAME IN ('kanban_select_more_v4_lead_0','kanban_edit_more_v4_lead_0')"
);
while ($kanbanRows && ($row = $kanbanRows->fetch())) {
	file_put_contents($backup . '/kanban_' . (int)$row['ID'] . '.ser', (string)$row['VALUE']);
	$cfg = @unserialize((string)$row['VALUE'], ['allowed_classes' => false]);
	if (!is_array($cfg)) {
		say('kanban option ' . $row['ID'] . ' did not unserialize');
		continue;
	}
	$next = addKanban($cfg, $fields);
	\CUserOptions::SetOption('crm', (string)$row['NAME'], $next, (string)$row['COMMON'] === 'Y', (int)$row['USER_ID']);
	say('kanban ' . $row['NAME'] . ' user=' . $row['USER_ID']);
}

$commonName = 'kanban_select_more_v4_lead_0_common';
$commonRow = $conn->query(
	"SELECT ID, VALUE FROM b_user_option WHERE USER_ID=0 AND CATEGORY='crm' AND NAME='{$commonName}' LIMIT 1"
)->fetch();
if (is_array($commonRow) && $commonRow['VALUE'] !== '') {
	file_put_contents($backup . '/kanban_common.ser', (string)$commonRow['VALUE']);
	$cfg = @unserialize((string)$commonRow['VALUE'], ['allowed_classes' => false]);
	if (!is_array($cfg)) {
		say('kanban common did not unserialize');
		$cfg = [];
	}
} else {
	$cfg = [
		'TITLE' => '',
		'OPPORTUNITY' => '',
		'DATE_CREATE' => '',
		'CLIENT' => '',
		'LAST_ACTIVITY_BY_TIME' => '',
		'LAST_ACTIVITY_BY_USER_AVATAR' => '',
	];
}
\CUserOptions::SetOption('crm', $commonName, addKanban($cfg, $fields), true, 0);
say('kanban common saved');

$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$marker = 'A7_BOOKING_STAGE_FIELDS';
$initBlock = "\n// A7_BOOKING_STAGE_FIELDS: five booking fields only on the Booking stage.\n"
	. "if (is_file(__DIR__ . '/include/a7_booking_stage_fields.php')) {\n"
	. "    require_once __DIR__ . '/include/a7_booking_stage_fields.php';\n"
	. "}\n";
$initText = is_file($init) ? (string)file_get_contents($init) : '';
if (str_contains($initText, $marker)) {
	say('init already hooked');
} elseif ($initText !== '' && is_writable($init)) {
	file_put_contents($init, $initText . $initBlock);
	say('init hooked');
} else {
	$fallback = '/home/bitrix/www/bitrix/php_interface/include/a7_commission_doc.php';
	$fallbackText = is_file($fallback) ? (string)file_get_contents($fallback) : '';
	$fallbackBlock = "\n// A7_BOOKING_STAGE_FIELDS\n"
		. "if (is_file(__DIR__ . '/a7_booking_stage_fields.php')) {\n"
		. "    require_once __DIR__ . '/a7_booking_stage_fields.php';\n"
		. "}\n";
	if ($fallbackText !== '' && !str_contains($fallbackText, $marker) && is_writable($fallback)) {
		file_put_contents($fallback, $fallbackText . $fallbackBlock);
		say('hooked from commission doc; init not writable');
	} else {
		say('HOOK FAILED init writable=' . (is_writable($init) ? 'yes' : 'no'));
		exit(1);
	}
}

say('--- webhook ids ---');
foreach ($fields as $name) {
	$row = fieldRow($name);
	say($name . ' user_field_id=' . ($row['ID'] ?? '?'));
	if ($row && (string)$row['USER_TYPE_ID'] === 'enumeration') {
		foreach (enumMap((int)$row['ID']) as $value => $meta) {
			say('  ' . $value . '=' . $meta['id']);
		}
	}
}
say('backup ' . $backup);
say('DONE');
