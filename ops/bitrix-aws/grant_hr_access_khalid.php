<?php
/**
 * Give Furqan Khalid (2632 / furqan.a7group@gmail.com) the same HR CRM
 * roles as Usman (44 HR + 45 hr), plus the two HR-section pages role 45
 * was missing: Recruitment Request 1160 and Agent's Profile 1172.
 *
 * Already in HR dept 58 + group 9. Not given CRM Administrator role 3.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

const USER_ID = 2632;
const HR_DEPT = 58;
const HR_GROUP = 9;
const ROLES = [44, 45];
const EXPECTED_EMAIL = 'furqan.a7group@gmail.com';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$userRow = $m->query('SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID=' . USER_ID)->fetch_assoc();
if (!$userRow || $userRow['ACTIVE'] !== 'Y') {
	fwrite(STDERR, "User 2632 missing or inactive\n");
	exit(1);
}
if (strcasecmp((string) $userRow['EMAIL'], EXPECTED_EMAIL) !== 0) {
	fwrite(STDERR, "Refusing: user 2632 email is {$userRow['EMAIL']}\n");
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

$copies = [
	'DYNAMIC_1156_C44' => 'DYNAMIC_1160_C45',
	'DYNAMIC_1168_C47' => 'DYNAMIC_1172_C48',
];
foreach ($copies as $fromEntity => $toEntity) {
	$have = $m->query(
		"SELECT COUNT(*) c FROM b_crm_role_perms WHERE ROLE_ID=45 AND ENTITY='"
		. $m->real_escape_string($toEntity) . "'"
	)->fetch_assoc();
	if ((int) $have['c'] > 0) {
		echo "already perms $toEntity\n";
		continue;
	}
	$src = $m->query(
		"SELECT FIELD, PERM_TYPE, ATTR, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=45 AND ENTITY='"
		. $m->real_escape_string($fromEntity) . "'"
	);
	$n = 0;
	while ($row = $src->fetch_assoc()) {
		$field = $row['FIELD'] === null ? 'NULL' : "'" . $m->real_escape_string($row['FIELD']) . "'";
		$attr = $row['ATTR'] === null ? 'NULL' : "'" . $m->real_escape_string($row['ATTR']) . "'";
		$settings = $row['SETTINGS'] === null ? 'NULL' : "'" . $m->real_escape_string($row['SETTINGS']) . "'";
		$m->query(
			'INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, PERM_TYPE, ATTR, SETTINGS) VALUES (45, \''
			. $m->real_escape_string($toEntity) . "', $field, '"
			. $m->real_escape_string($row['PERM_TYPE']) . "', $attr, $settings)"
		);
		$n++;
	}
	echo "copied $fromEntity -> $toEntity rows=$n\n";
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
try {
	\Bitrix\Crm\Security\Role\Model\RolePermissionTable::getEntity()->cleanCache();
} catch (Throwable $e) {
	echo 'role cache: ' . $e->getMessage() . "\n";
}
echo "cache cleared\n";

$perms = new CCrmPerms(USER_ID);
foreach (['DYNAMIC_1168', 'DYNAMIC_1168_C47', 'DYNAMIC_1160', 'DYNAMIC_1160_C45', 'DYNAMIC_1156', 'DYNAMIC_1156_C44', 'DYNAMIC_1172', 'DYNAMIC_1172_C48'] as $ent) {
	echo $ent
		. ' R=' . $perms->GetPermType($ent, 'READ')
		. ' W=' . $perms->GetPermType($ent, 'WRITE')
		. "\n";
}

echo "=== modern perms ===\n";
$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions(USER_ID);
$et = $up->entityType();
foreach ([1156, 1160, 1168, 1172] as $type) {
	echo $type . ' read=' . ($et->canReadItems($type) ? 'Y' : 'N') . "\n";
}

echo "=== relations now ===\n";
$q = $m->query("SELECT ROLE_ID FROM b_crm_role_relation WHERE RELATION='U" . USER_ID . "' ORDER BY ROLE_ID");
while ($r = $q->fetch_assoc()) {
	echo 'ROLE ' . $r['ROLE_ID'] . "\n";
}
echo "DONE\n";
