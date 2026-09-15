#!/usr/bin/env php
<?php
/**
 * Probe why agents get Access denied on Owner Data (1042) kanban.
 * Focus: mehnaz 2381 + sample agents vs heads on C13/C14.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$users = [
	2381 => 'mehnaz (agent)',
	2367 => 'Warda (agent)',
	2291 => 'Uzma (agent)',
	2560 => 'Hassan TL',
	2551 => 'Hussnain TL',
	1 => 'Admin',
];

echo "=== CRM roles assigned to users ===\n";
foreach ($users as $uid => $label) {
	$q = $m->query(
		"SELECT r.ID, r.NAME, rel.RELATION
		 FROM b_crm_role_relation rel
		 JOIN b_crm_role r ON r.ID = rel.ROLE_ID
		 WHERE rel.RELATION LIKE 'U{$uid}' OR rel.RELATION LIKE 'IU{$uid}'
		    OR rel.RELATION IN (
		      SELECT GROUP_CODE FROM b_user_access WHERE USER_ID={$uid}
		    )
		 ORDER BY r.ID"
	);
	$roles = [];
	if ($q) {
		while ($r = $q->fetch_assoc()) {
			$roles[] = $r['ID'] . ':' . $r['NAME'] . '(' . $r['RELATION'] . ')';
		}
	}
	// Also direct: all role relations that match this user's access codes
	$codes = [];
	$cq = $m->query("SELECT ACCESS_CODE FROM b_user_access WHERE USER_ID=" . (int)$uid);
	while ($c = $cq->fetch_assoc()) {
		$codes[] = $c['ACCESS_CODE'];
	}
	$roleVia = [];
	if ($codes) {
		$in = implode(',', array_map(static fn($c) => "'" . $m->real_escape_string($c) . "'", $codes));
		$q2 = $m->query(
			"SELECT DISTINCT r.ID, r.NAME, rel.RELATION
			 FROM b_crm_role_relation rel
			 JOIN b_crm_role r ON r.ID = rel.ROLE_ID
			 WHERE rel.RELATION IN ($in)
			 ORDER BY r.ID"
		);
		while ($r = $q2->fetch_assoc()) {
			$roleVia[] = $r['ID'] . ':' . $r['NAME'] . '@' . $r['RELATION'];
		}
	}
	echo "$label ($uid) codes=" . count($codes) . " roles=" . json_encode($roleVia) . "\n";
}

echo "\n=== All CRM roles ===\n";
$q = $m->query('SELECT ID, NAME FROM b_crm_role ORDER BY ID');
while ($r = $q->fetch_assoc()) {
	echo $r['ID'] . "\t" . $r['NAME'] . "\n";
}

echo "\n=== Role perms for DYNAMIC_1042 (any category) — all roles ===\n";
$q = $m->query(
	"SELECT ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR
	 FROM b_crm_role_perms
	 WHERE ENTITY LIKE '%1042%'
	 ORDER BY ROLE_ID, ENTITY, PERM_TYPE, FIELD"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "\n=== Permission checks via API ===\n";
foreach ($users as $uid => $label) {
	echo "---- $label ($uid) ----\n";
	try {
		$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
		foreach ([13, 14] as $cat) {
			$entity = "DYNAMIC_1042_C{$cat}";
			$canRead = method_exists($up, 'entityType')
				? null
				: null;
			// Modern API
			$itemPerms = $up->item();
			$canOpen = '?';
			try {
				// category-aware read
				if (method_exists($up, 'canReadType')) {
					$canOpen = $up->canReadType(1042) ? 'Y' : 'N';
				}
			} catch (Throwable $e) {
				$canOpen = 'err:' . $e->getMessage();
			}

			$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
			$level = $pm->getPermissionLevel($entity, 'READ');
			echo "  $entity READ hasPerm=" . ($level->hasPermission() ? 'Y' : 'N')
				. " max=" . ($level->hasMaxPermissionLevel() ? 'Y' : 'N')
				. " attrs=" . json_encode($level->getEntityAttributesToCheckInListMode())
				. " canReadType=" . json_encode($canOpen)
				. "\n";

			$w = $pm->getPermissionLevel($entity, 'WRITE');
			echo "  $entity WRITE hasPerm=" . ($w->hasPermission() ? 'Y' : 'N')
				. " attrs=" . json_encode($w->getEntityAttributesToCheckInListMode())
				. "\n";
		}

		// Kanban access helper
		if (class_exists(\Bitrix\Crm\Service\UserPermissions\EntityPermissions\Category::class)) {
			echo "  Category class exists\n";
		}
		$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
		foreach ([13, 14] as $cat) {
			$ok = $up->entityType()->canReadItemsInCategory(1042, $cat);
			echo "  canReadItemsInCategory($cat)=" . ($ok ? 'Y' : 'N') . "\n";
		}
		$okType = $up->entityType()->canReadItems(1042);
		echo "  canReadItems(1042)=" . ($okType ? 'Y' : 'N') . "\n";
	} catch (Throwable $e) {
		echo "  ERR: " . $e->getMessage() . "\n" . $e->getTraceAsString() . "\n";
	}
}

echo "\n=== Role relations for employee group / department codes sample ===\n";
$q = $m->query(
	"SELECT rel.ROLE_ID, r.NAME, rel.RELATION, COUNT(*) c
	 FROM b_crm_role_relation rel
	 JOIN b_crm_role r ON r.ID=rel.ROLE_ID
	 GROUP BY rel.ROLE_ID, r.NAME, rel.RELATION
	 ORDER BY rel.ROLE_ID, rel.RELATION
	 LIMIT 80"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}
