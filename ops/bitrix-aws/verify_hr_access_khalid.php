<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

BXClearCache(true, '/crm/');
$managed = \Bitrix\Main\Application::getInstance()->getManagedCache();
$managed->cleanDir('/crm/');
$managed->cleanDir('/crm/user_permission_roles/');
$managed->cleanDir('/crm/user_access_codes/');
try {
	\Bitrix\Crm\Security\Role\Model\RolePermissionTable::getEntity()->cleanCache();
} catch (Throwable $e) {
	echo 'role cache: ' . $e->getMessage() . "\n";
}

$access = new CAccess();
$access->UpdateCodes(['USER_ID' => 2632]);

echo "=== user 2632 ===\n";
$u = $m->query("SELECT ID, EMAIL, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID=2632")->fetch_assoc();
echo json_encode($u) . "\n";

echo "=== relations ===\n";
$q = $m->query("SELECT rr.ROLE_ID, r.NAME FROM b_crm_role_relation rr JOIN b_crm_role r ON r.ID=rr.ROLE_ID WHERE rr.RELATION='U2632'");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== modern perms ===\n";
foreach ([2632, 2628, 2319] as $uid) {
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$et = $up->entityType();
	echo "uid=$uid";
	foreach ([1156, 1160, 1168, 1172] as $type) {
		echo "  $type=" . ($et->canReadItems($type) ? 'Y' : 'N');
	}
	echo "\n";
}

echo "DONE\n";
