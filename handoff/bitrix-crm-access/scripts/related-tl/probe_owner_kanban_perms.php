<?php
/**
 * Probe why Owner Data cat 13 kanban still shows everyone for TLs.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$heads = [2560 => 'Hassan', 2551 => 'Hussnain', 2297 => 'Jaweria'];
$agents = [
	2560 => [2380, 2344, 2434, 2291, 2378, 2376, 2379, 2303, 2560],
	2551 => [2381, 2369, 2371, 2535, 2368, 2367, 2351, 2350, 2551],
	2297 => [2299, 2302, 2392, 2298, 2390, 2297],
];

echo "=== role 54 C13 perms (all fields) ===\n";
$q = $m->query(
	"SELECT ID,ENTITY,FIELD,FIELD_VALUE,PERM_TYPE,ATTR,SETTINGS
	 FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY LIKE '%1042%'
	 ORDER BY ENTITY,PERM_TYPE,FIELD"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== access attr sample for owner items ===\n";
$q = $m->query('SHOW COLUMNS FROM b_crm_access_attr_dynamic_1042');
while ($c = $q->fetch_assoc()) {
	echo $c['Field'] . ' ';
}
echo "\n";

// How many opened vs closed for cat 13
$q = $m->query(
	"SELECT i.OPENED, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 WHERE i.CATEGORY_ID=13 GROUP BY i.OPENED"
);
while ($r = $q->fetch_assoc()) {
	echo 'items OPENED=' . json_encode($r) . "\n";
}

// Access attr opened flags
$q = $m->query(
	"SELECT a.IS_OPENED, COUNT(*) c
	 FROM b_crm_access_attr_dynamic_1042 a
	 WHERE a.CATEGORY_ID=13 GROUP BY a.IS_OPENED"
);
while ($r = $q->fetch_assoc()) {
	echo 'attr IS_OPENED=' . json_encode($r) . "\n";
}

foreach ($heads as $uid => $name) {
	echo "==== $name ($uid) list attrs ====\n";
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$level = $pm->getPermissionLevel('DYNAMIC_1042_C13', 'READ');
	$attrs = $level->getEntityAttributesToCheckInListMode();
	echo 'listAttrs=' . json_encode($attrs) . "\n";
	echo 'hasMax=' . ($level->hasMaxPermissionLevel() ? 'Y' : 'N') . "\n";
	echo 'hasPerm=' . ($level->hasPermission() ? 'Y' : 'N') . "\n";

	// Build SQL via itemsList
	try {
		$builder = $up->itemsList()->createQueryBuilder('DYNAMIC_1042_C13');
		$sql = $builder->build();
		echo 'sql type=' . gettype($sql) . "\n";
		if (is_array($sql)) {
			echo 'sql keys=' . json_encode(array_keys($sql)) . "\n";
			echo 'sql=' . substr(json_encode($sql), 0, 1500) . "\n";
		} elseif (is_object($sql) && method_exists($sql, '__toString')) {
			echo (string)$sql . "\n";
		} else {
			echo substr(print_r($sql, true), 0, 1500) . "\n";
		}
	} catch (Throwable $e) {
		echo 'builder err: ' . $e->getMessage() . "\n";
	}

	// Count items readable via factory getItemsRestricted
	try {
		$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
		$filter = [
			'CATEGORY_ID' => 13,
		];
		// Use getItems with permission check
		$items = $factory->getItems([
			'select' => ['ID', 'ASSIGNED_BY_ID'],
			'filter' => $filter,
			'limit' => 50,
			'order' => ['ID' => 'DESC'],
		]);
		// That ignores perms. Use DataManager with permission filter:
		$params = [
			'select' => ['ID', 'ASSIGNED_BY_ID'],
			'filter' => ['CATEGORY_ID' => 13],
			'limit' => 30,
			'order' => ['ID' => 'DESC'],
		];
		$dataClass = $factory->getDataClass();
		// Apply permission via UserPermissions
		$filterWithPerm = $up->itemsList()->applyPermissionsToFilter(
			'DYNAMIC_1042_C13',
			$params['filter'] ?? []
		);
		echo 'filterWithPerm methods...' . "\n";
	} catch (Throwable $e) {
		echo 'count err: ' . $e->getMessage() . "\n";
	}

	// Direct: how many cat13 assigned to team vs total visible by attr join
	$team = implode(',', array_map('intval', $agents[$uid]));
	$q = $m->query(
		"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
		 WHERE CATEGORY_ID=13 AND ASSIGNED_BY_ID IN ($team)"
	);
	echo 'teamAssignedCount=' . $q->fetch_assoc()['c'] . "\n";
	$q = $m->query('SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=13');
	echo 'allCat13=' . $q->fetch_assoc()['c'] . "\n";

	// Simulate list: entities matching list attrs via access table
	// USER_ID in team OR IS_OPENED if open perm
	$q = $m->query(
		"SELECT COUNT(DISTINCT a.ENTITY_ID) c
		 FROM b_crm_access_attr_dynamic_1042 a
		 WHERE a.CATEGORY_ID=13 AND a.USER_ID IN ($team)"
	);
	echo 'attrTeamCount=' . $q->fetch_assoc()['c'] . "\n";
	$q = $m->query(
		"SELECT COUNT(DISTINCT a.ENTITY_ID) c
		 FROM b_crm_access_attr_dynamic_1042 a
		 WHERE a.CATEGORY_ID=13 AND a.IS_OPENED='Y'"
	);
	echo 'attrOpenedCount=' . $q->fetch_assoc()['c'] . "\n";
}
