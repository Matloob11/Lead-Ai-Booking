<?php
/**
 * Give HR Request access to HR Usman (2628).
 * Already in HR dept 58 + group 9. Missing CRM roles 44 (HR) and 45 (hr),
 * which existing HR staff use. 45 holds DYNAMIC_1168_C47 (HR Request) ALL.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

const USER_ID = 2628;
const HR_DEPT = 58;
const HR_GROUP = 9;
const ROLES = [44, 45];

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$userRow = $m->query('SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID=' . USER_ID)->fetch_assoc();
if (!$userRow || $userRow['ACTIVE'] !== 'Y') {
	fwrite(STDERR, "User 2628 missing or inactive\n");
	exit(1);
}
if (stripos($userRow['EMAIL'], 'usman.a7group@gmail.com') === false) {
	fwrite(STDERR, "Refusing: user 2628 email is {$userRow['EMAIL']}\n");
	exit(1);
}
echo 'user=' . json_encode($userRow) . "\n";

$user = new CUser();
$ok = $user->Update(USER_ID, ['UF_DEPARTMENT' => [HR_DEPT]]);
echo ($ok ? 'ok' : 'FAIL') . " UF_DEPARTMENT=" . HR_DEPT . ' ' . $user->LAST_ERROR . "\n";

$inGroup = $m->query('SELECT COUNT(*) c FROM b_user_group WHERE USER_ID=' . USER_ID . ' AND GROUP_ID=' . HR_GROUP);
$inGroupN = $inGroup ? (int) $inGroup->fetch_assoc()['c'] : 0;
if ($inGroupN < 1) {
	$m->query('INSERT INTO b_user_group (USER_ID, GROUP_ID) VALUES (' . USER_ID . ',' . HR_GROUP . ')');
	echo "inserted group " . HR_GROUP . "\n";
} else {
	echo "already group " . HR_GROUP . "\n";
}

foreach (ROLES as $roleId) {
	$rel = 'U' . USER_ID;
	$exists = $m->query(
		'SELECT ID FROM b_crm_role_relation WHERE ROLE_ID=' . (int) $roleId
		. " AND RELATION='" . $m->real_escape_string($rel) . "'"
	)->fetch_assoc();
	if ($exists) {
		echo "already role $roleId\n";
		continue;
	}
	$m->query(
		'INSERT INTO b_crm_role_relation (ROLE_ID, RELATION) VALUES ('
		. (int) $roleId . ", '" . $m->real_escape_string($rel) . "')"
	);
	echo "inserted role $roleId id=" . $m->insert_id . "\n";
}

$access = new CAccess();
$access->UpdateCodes(['USER_ID' => USER_ID]);
echo "codes rebuilt\n";

if (function_exists('BXClearCache')) {
	BXClearCache(true);
}
if (class_exists(\Bitrix\Main\Application::class)) {
	\Bitrix\Main\Application::getInstance()->getManagedCache()->cleanAll();
}
echo "cache cleared\n";

$perms = new CCrmPerms(USER_ID);
foreach (['DYNAMIC_1168', 'DYNAMIC_1168_C47', 'DYNAMIC_1160', 'DYNAMIC_1156', 'DYNAMIC_1156_C44'] as $ent) {
	echo $ent
		. ' R=' . $perms->GetPermType($ent, 'READ')
		. ' W=' . $perms->GetPermType($ent, 'WRITE')
		. "\n";
}

echo "=== relations now ===\n";
$q = $m->query("SELECT ROLE_ID FROM b_crm_role_relation WHERE RELATION='U" . USER_ID . "' ORDER BY ROLE_ID");
while ($r = $q->fetch_assoc()) {
	echo 'ROLE ' . $r['ROLE_ID'] . "\n";
}
echo "DONE\n";
