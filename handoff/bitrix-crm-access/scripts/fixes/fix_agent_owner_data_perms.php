#!/usr/bin/env php
<?php
/**
 * Fix: agents (CRM role 36 "Agent" via group G11) get Access denied on Owner Data.
 * Role 36 had ZERO DYNAMIC_1042_* perms. Mirror Sales Agent (role 8) personal scope (ATTR=A).
 * Categories: 13 Owner Data + 14 Availability.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
	fwrite(STDERR, "DB connect fail\n");
	exit(1);
}

$ROLE = 36; // Agent @ G11

function upsertPerm(mysqli $m, int $roleId, string $entity, string $permType, ?string $attr, ?string $settings, string $field = '-', ?string $fieldValue = null): void
{
	$e = $m->real_escape_string($entity);
	$p = $m->real_escape_string($permType);
	$f = $m->real_escape_string($field);
	$fvSql = $fieldValue === null ? 'IS NULL' : ("='" . $m->real_escape_string($fieldValue) . "'");
	$q = $m->query(
		"SELECT ID FROM b_crm_role_perms
		 WHERE ROLE_ID=$roleId AND ENTITY='$e' AND PERM_TYPE='$p' AND FIELD='$f' AND FIELD_VALUE $fvSql
		 LIMIT 1"
	);
	$row = $q ? $q->fetch_assoc() : null;
	$attrSql = $attr === null ? 'NULL' : ("'" . $m->real_escape_string($attr) . "'");
	$settingsSql = $settings === null ? 'NULL' : ("'" . $m->real_escape_string($settings) . "'");
	$fvIns = $fieldValue === null ? 'NULL' : ("'" . $m->real_escape_string($fieldValue) . "'");

	if ($row) {
		$id = (int)$row['ID'];
		$m->query("UPDATE b_crm_role_perms SET ATTR=$attrSql, SETTINGS=$settingsSql WHERE ID=$id");
		echo "UPD $entity $permType field=$field id=$id attr=" . json_encode($attr) . " settings=" . json_encode($settings) . "\n";
	} else {
		$m->query(
			"INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS)
			 VALUES ($roleId, '$e', '$f', $fvIns, '$p', $attrSql, $settingsSql)"
		);
		echo "INS $entity $permType field=$field id=" . $m->insert_id . " attr=" . json_encode($attr) . "\n";
	}
}

echo "=== BEFORE role $ROLE 1042 ===\n";
$q = $m->query("SELECT ENTITY,PERM_TYPE,ATTR,SETTINGS,FIELD,FIELD_VALUE FROM b_crm_role_perms WHERE ROLE_ID=$ROLE AND ENTITY LIKE '%1042%' ORDER BY ENTITY, PERM_TYPE, FIELD");
$n = 0;
while ($r = $q->fetch_assoc()) {
	$n++;
	echo json_encode($r) . "\n";
}
echo "count=$n\n";

// Base entity + both categories — personal only (own assigned cards)
$entities = ['DYNAMIC_1042', 'DYNAMIC_1042_C13', 'DYNAMIC_1042_C14'];
foreach ($entities as $entity) {
	upsertPerm($m, $ROLE, $entity, 'READ', 'A', '[]');
	upsertPerm($m, $ROLE, $entity, 'WRITE', 'A', '[]');
	upsertPerm($m, $ROLE, $entity, 'ADD', 'A', '[]');
	upsertPerm($m, $ROLE, $entity, 'HIDE_SUM', 'X', '[]');
	upsertPerm($m, $ROLE, $entity, 'MYCARDVIEW', 'X', '[]');
	upsertPerm($m, $ROLE, $entity, 'TRANSITION', null, '["ANY"]');
}

// Stage-level READ for Availability (C14) — same stages as Sales Agent role 8
$stages = [];
$sq = $m->query(
	"SELECT DISTINCT FIELD_VALUE FROM b_crm_role_perms
	 WHERE ROLE_ID=8 AND ENTITY='DYNAMIC_1042_C14' AND FIELD='STAGE_ID' AND PERM_TYPE='READ'
	   AND FIELD_VALUE IS NOT NULL"
);
while ($r = $sq->fetch_assoc()) {
	$stages[] = $r['FIELD_VALUE'];
}
if (!$stages) {
	// fallback from status table
	$sq = $m->query("SELECT STATUS_ID FROM b_crm_status WHERE ENTITY_ID='DYNAMIC_1042_STAGE_14' ORDER BY SORT");
	while ($r = $sq->fetch_assoc()) {
		$stages[] = $r['STATUS_ID'];
	}
}
foreach ($stages as $st) {
	upsertPerm($m, $ROLE, 'DYNAMIC_1042_C14', 'READ', 'A', 'null', 'STAGE_ID', $st);
}

echo "=== AFTER role $ROLE 1042 ===\n";
$q = $m->query("SELECT ENTITY,PERM_TYPE,ATTR,SETTINGS,FIELD,FIELD_VALUE FROM b_crm_role_perms WHERE ROLE_ID=$ROLE AND ENTITY LIKE '%1042%' ORDER BY ENTITY, PERM_TYPE, FIELD, FIELD_VALUE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

// Clear permission / role caches
echo "=== clear caches ===\n";
if (class_exists(\Bitrix\Crm\Security\Role\RolePermission::class)) {
	try {
		// touch
		echo "RolePermission class ok\n";
	} catch (Throwable $e) {
	}
}
if (function_exists('BXClearCache')) {
	BXClearCache(true);
	echo "BXClearCache done\n";
}
$cache = \Bitrix\Main\Application::getInstance()->getManagedCache();
$cache->cleanAll();
echo "managedCache cleanAll done\n";

// Reset PermissionsManager statics if possible
if (method_exists(\Bitrix\Crm\Security\Role\PermissionsManager::class, 'getInstance')) {
	echo "PermissionsManager ready for re-check\n";
}

$checkUsers = [
	2381 => 'mehnaz',
	2367 => 'Warda',
	2291 => 'Uzma',
	2560 => 'Hassan TL',
	2551 => 'Hussnain TL',
];

echo "=== VERIFY canRead ===\n";
foreach ($checkUsers as $uid => $name) {
	// Fresh manager instance
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$c13 = $up->entityType()->canReadItemsInCategory(1042, 13) ? 'Y' : 'N';
	$c14 = $up->entityType()->canReadItemsInCategory(1042, 14) ? 'Y' : 'N';
	$l13 = $pm->getPermissionLevel('DYNAMIC_1042_C13', 'READ');
	$l14 = $pm->getPermissionLevel('DYNAMIC_1042_C14', 'READ');
	echo "$name ($uid) C13=$c13 C14=$c14 "
		. "attrs13=" . json_encode($l13->getEntityAttributesToCheckInListMode())
		. " attrs14=" . json_encode($l14->getEntityAttributesToCheckInListMode())
		. "\n";
}

// Count mehnaz assigned items
$uid = 2381;
$q = $m->query("SELECT CATEGORY_ID, COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE ASSIGNED_BY_ID=$uid GROUP BY CATEGORY_ID");
echo "=== mehnaz assigned Owner Data cards ===\n";
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "DONE — agents should re-login / hard refresh Owner Data\n";
