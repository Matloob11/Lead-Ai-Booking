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
$access->UpdateCodes(['USER_ID' => 2628]);

echo "=== relations ===\n";
$q = $m->query("SELECT rr.ROLE_ID, r.NAME FROM b_crm_role_relation rr JOIN b_crm_role r ON r.ID=rr.ROLE_ID WHERE rr.RELATION='U2628'");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== modern perms ===\n";
foreach ([2628, 2319, 2243] as $uid) {
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$et = $up->entityType();
	echo "uid=$uid";
	foreach ([1168, 1160, 1156, 1172] as $type) {
		$read = $et->canReadItems($type) ? 'Y' : 'N';
		$cat = method_exists($et, 'canReadItemsInCategory') ? ($et->canReadItemsInCategory($type, 47) ? 'Y' : 'N') : '?';
		echo "  $type read=$read";
		if ($type === 1168) {
			echo " c47=$cat";
		}
	}
	echo "\n";
}

echo "=== 1168 categories ===\n";
$q = $m->query("SELECT ID, NAME, ENTITY_TYPE_ID, IS_DEFAULT FROM b_crm_item_category WHERE ENTITY_TYPE_ID=1168");
if ($q) {
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
} else {
	echo $m->error . "\n";
	$q = $m->query("SHOW TABLES LIKE '%categor%'");
	while ($r = $q->fetch_row()) {
		echo $r[0] . "\n";
	}
}

echo "DONE\n";
