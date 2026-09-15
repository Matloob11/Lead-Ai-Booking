#!/usr/bin/env php
<?php
/**
 * Grant Agent role 36 personal CRM access (LEAD + CONTACT + COMPANY + DEAL + QUOTE)
 * mirroring Sales Agent role 8. Fixes Access Denied on /crm/lead/list/ for agents.
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
	fwrite(STDERR, "DB fail\n");
	exit(1);
}

$ROLE = 36;

function upsertPerm(
	mysqli $m,
	int $roleId,
	string $entity,
	string $permType,
	?string $attr,
	?string $settings,
	string $field = '-',
	?string $fieldValue = null
): void {
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
		echo "UPD $entity $permType\n";
	} else {
		$m->query(
			"INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS)
			 VALUES ($roleId, '$e', '$f', $fvIns, '$p', $attrSql, $settingsSql)"
		);
		echo "INS $entity $permType id={$m->insert_id}\n";
	}
}

// Copy exact pattern from role 8 for core CRM entities agents need
$spec = [
	// LEAD
	['LEAD', 'READ', 'A', '[]'],
	['LEAD', 'WRITE', 'A', '[]'],
	['LEAD', 'ADD', 'A', '[]'],
	['LEAD', 'HIDE_SUM', 'X', '[]'],
	['LEAD', 'MYCARDVIEW', 'X', '[]'],
	['LEAD', 'TRANSITION', null, '["ANY"]'],
	['LEAD', 'IMPORT', null, '["SELF"]'],
	// CONTACT
	['CONTACT', 'READ', 'A', '[]'],
	['CONTACT', 'WRITE', 'A', '[]'],
	['CONTACT', 'ADD', 'A', '[]'],
	['CONTACT', 'MYCARDVIEW', 'X', '[]'],
	// COMPANY
	['COMPANY', 'READ', 'A', '[]'],
	['COMPANY', 'WRITE', 'A', '[]'],
	['COMPANY', 'ADD', 'A', '[]'],
	['COMPANY', 'MYCARDVIEW', 'X', '[]'],
	// DEAL
	['DEAL', 'READ', 'A', '[]'],
	['DEAL', 'WRITE', 'A', '[]'],
	['DEAL', 'ADD', 'A', '[]'],
	['DEAL', 'HIDE_SUM', 'X', '[]'],
	['DEAL', 'MYCARDVIEW', 'X', '[]'],
	['DEAL', 'TRANSITION', null, '["ANY"]'],
	// QUOTE (view helpers like role 8)
	['QUOTE', 'HIDE_SUM', 'X', '[]'],
	['QUOTE', 'MYCARDVIEW', 'X', '[]'],
	['QUOTE', 'TRANSITION', null, '["ANY"]'],
];

echo "=== apply to role $ROLE ===\n";
foreach ($spec as [$entity, $ptype, $attr, $settings]) {
	upsertPerm($m, $ROLE, $entity, $ptype, $attr, $settings);
}

echo "=== clear caches ===\n";
if (function_exists('BXClearCache')) {
	BXClearCache(true);
}
\Bitrix\Main\Application::getInstance()->getManagedCache()->cleanAll();
echo "cache cleared\n";

$check = [2291 => 'Uzma', 2381 => 'mehnaz', 2367 => 'Warda', 2299 => 'Farhat', 2560 => 'Hassan'];
echo "=== VERIFY ===\n";
foreach ($check as $uid => $name) {
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$lead = $up->entityType()->canReadItems(\CCrmOwnerType::Lead) ? 'Y' : 'N';
	$contact = $up->entityType()->canReadItems(\CCrmOwnerType::Contact) ? 'Y' : 'N';
	$deal = $up->entityType()->canReadItems(\CCrmOwnerType::Deal) ? 'Y' : 'N';
	$od = $up->entityType()->canReadItems(1042) ? 'Y' : 'N';
	$attrs = $pm->getPermissionLevel('LEAD', 'READ')->getEntityAttributesToCheckInListMode();
	echo "$name ($uid) LEAD=$lead CONTACT=$contact DEAL=$deal OD=$od attrs=" . json_encode($attrs) . "\n";
}

echo "DONE — agents: logout/login or hard refresh Leads\n";
