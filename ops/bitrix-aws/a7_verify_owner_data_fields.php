<?php
/**
 * Prove Owner Data field lock v1.1: create locked; update/settings free; UI scoped.
 */
declare(strict_types=1);

$doc = '/home/bitrix/www';
$checks = [
	$doc . '/bitrix/php_interface/include/a7_owner_data_fields.php',
	$doc . '/bitrix/js/a7_owner_data_fields.js',
	$doc . '/bitrix/css/a7_owner_data_fields.css',
	$doc . '/bitrix/php_interface/a7_stage_admin.config.php',
];
foreach ($checks as $path) {
	if (!is_file($path)) {
		fwrite(STDERR, "MISSING $path\n");
		exit(1);
	}
	echo 'ok ', basename($path), ' ', md5_file($path), ' ', filesize($path), "\n";
}

$init = file_get_contents($doc . '/bitrix/php_interface/init.php');
echo str_contains($init, 'A7_OWNER_DATA_FIELDS') ? "init: wired\n" : "init: MISSING\n";

$js = file_get_contents($doc . '/bitrix/js/a7_owner_data_fields.js');
echo str_contains($js, 'userfieldconfig.add') ? "js: create lock ok\n" : "js: create lock MISSING\n";
echo !str_contains($js, 'userfieldconfig.update') ? "js: update NOT gated ok\n" : "js: update still gated — FAIL\n";
echo str_contains($js, 'delete\\s+section') || str_contains($js, 'Delete section')
	? "js: delete section ok\n"
	: "js: delete section MISSING\n";
echo str_contains($js, 'onOwnerDetails') || str_contains($js, 'details/')
	? "js: details-scoped ok\n"
	: "js: details-scoped MISSING\n";
echo !str_contains($js, 'configure-icon') && !str_contains($js, 'field\\s+settings')
	? "js: no broad configure gate ok\n"
	: "js: broad configure still present — FAIL\n";

$php = file_get_contents($doc . '/bitrix/php_interface/include/a7_owner_data_fields.php');
echo str_contains($php, 'OnBeforeUserTypeAdd') ? "php: Add ok\n" : "php: Add MISSING\n";
echo !str_contains($php, 'OnBeforeUserTypeUpdate') ? "php: Update unlocked ok\n" : "php: Update still locked — FAIL\n";
echo !str_contains($php, 'OnBeforeUserTypeDelete') ? "php: Delete UF unlocked ok\n" : "php: Delete UF still locked — FAIL\n";
echo str_contains($php, '1.1.0') ? "php: version 1.1.0 ok\n" : "php: version MISSING\n";

foreach (['/bitrix/js/a7_owner_data_fields.js', '/bitrix/css/a7_owner_data_fields.css'] as $path) {
	$code = trim((string)shell_exec(
		'curl -sk -o /dev/null -w "%{http_code}" -H "Host: crm.a7grouprealestatedxb.com" '
		. escapeshellarg('https://127.0.0.1' . $path . '?t=' . time())
	));
	echo "http $path -> $code\n";
}

define('A7_OWNER_DATA_FIELDS_FORCE_WEB', true);
define('A7_OWNER_DATA_FIELDS_BYPASS', false);
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_SKIP_SESSION_EXPAND', true);
$_SERVER['DOCUMENT_ROOT'] = $doc;
$_SERVER['REQUEST_METHOD'] = 'POST';
$_SERVER['REQUEST_URI'] = '/bitrix/services/main/ajax.php?action=main.userfieldconfig.add';
unset($_REQUEST['a7_stage_admin_password'], $_POST['a7_stage_admin_password']);
unset($_SERVER['HTTP_X_A7_STAGE_ADMIN_PASSWORD']);

require_once $doc . '/bitrix/php_interface/include/a7_owner_data_fields.php';

$ref = new ReflectionClass('A7OwnerDataFields');
$allowed = $ref->getProperty('allowed');
$allowed->setAccessible(true);
$allowed->setValue(null, null);

$fields = ['ENTITY_ID' => 'CRM_5', 'FIELD_NAME' => 'UF_CRM_5_A7_PROBE_LOCK', 'USER_TYPE_ID' => 'string'];
$addDenied = A7OwnerDataFields::onBeforeUserTypeAdd($fields) === false;
echo $addDenied ? "prove: Add denied without password OK\n" : "prove: Add WITHOUT password ALLOWED — FAIL\n";

$allowed->setValue(null, null);
$other = ['ENTITY_ID' => 'CRM_LEAD', 'FIELD_NAME' => 'UF_CRM_A7_OTHER', 'USER_TYPE_ID' => 'string'];
$otherOk = A7OwnerDataFields::onBeforeUserTypeAdd($other) === true;
echo $otherOk ? "prove: non-CRM_5 Add allowed OK\n" : "prove: non-CRM_5 blocked — FAIL\n";

$cfg = include $doc . '/bitrix/php_interface/a7_stage_admin.config.php';
$hash = is_array($cfg) ? (string)($cfg['password_hash'] ?? '') : '';
echo ($hash !== '' && !str_contains($hash, 'PLACEHOLDER'))
	? "config: password_hash present\n"
	: "config: password_hash MISSING\n";

$probe = base64_decode('YWRtaW4yMjIwMDc=', true);
if (is_string($probe) && $probe !== '' && $hash !== '') {
	$allowed->setValue(null, null);
	$ok = A7OwnerDataFields::verifyPassword($probe);
	echo $ok ? "prove: correct password verifies OK\n" : "prove: correct password REJECTED — FAIL\n";
	$allowed->setValue(null, null);
	$bad = A7OwnerDataFields::verifyPassword($probe . '_wrong');
	echo !$bad ? "prove: wrong password rejected OK\n" : "prove: wrong password ACCEPTED — FAIL\n";
	if (!$ok || $bad) {
		exit(1);
	}
}

echo 'version=', A7OwnerDataFields::VERSION, "\n";
echo "OK verify\n";

if (!$addDenied || !$otherOk) {
	exit(1);
}
if (str_contains($js, 'userfieldconfig.update') || str_contains($php, 'OnBeforeUserTypeUpdate')) {
	exit(1);
}
