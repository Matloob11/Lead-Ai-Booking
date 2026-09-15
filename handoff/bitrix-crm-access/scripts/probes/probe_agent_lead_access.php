#!/usr/bin/env php
<?php
/**
 * Probe Agent role 36 vs Sales Agent 8 for LEAD + common CRM entities.
 * Confirm Uzma 2291 / mehnaz 2381 still denied on LEAD.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== role 8 LEAD (+CONTACT DEAL) ===\n";
$q = $m->query(
	"SELECT ENTITY, FIELD, PERM_TYPE, ATTR, SETTINGS
	 FROM b_crm_role_perms
	 WHERE ROLE_ID=8 AND ENTITY IN ('LEAD','CONTACT','COMPANY','DEAL','QUOTE','INVOICE')
	 ORDER BY ENTITY, PERM_TYPE, FIELD"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "\n=== role 36 same entities ===\n";
$q = $m->query(
	"SELECT ENTITY, FIELD, PERM_TYPE, ATTR, SETTINGS
	 FROM b_crm_role_perms
	 WHERE ROLE_ID=36 AND ENTITY IN ('LEAD','CONTACT','COMPANY','DEAL','QUOTE','INVOICE')
	 ORDER BY ENTITY, PERM_TYPE, FIELD"
);
$n = 0;
while ($r = $q->fetch_assoc()) {
	$n++;
	echo json_encode($r) . "\n";
}
echo "count=$n\n";

echo "\n=== role 36 ALL entities summary ===\n";
$q = $m->query(
	"SELECT ENTITY, GROUP_CONCAT(DISTINCT PERM_TYPE ORDER BY PERM_TYPE) types, COUNT(*) c
	 FROM b_crm_role_perms WHERE ROLE_ID=36 GROUP BY ENTITY ORDER BY ENTITY"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

$users = [2291 => 'Uzma', 2381 => 'mehnaz', 2367 => 'Warda', 2560 => 'Hassan'];
echo "\n=== canRead checks ===\n";
foreach ($users as $uid => $name) {
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$lead = $up->entityType()->canReadItems(\CCrmOwnerType::Lead) ? 'Y' : 'N';
	$od = $up->entityType()->canReadItems(1042) ? 'Y' : 'N';
	$level = $pm->getPermissionLevel('LEAD', 'READ');
	echo "$name ($uid) LEAD=$lead 1042=$od leadAttrs=" . json_encode($level->getEntityAttributesToCheckInListMode()) . "\n";
}

echo "\n=== Uzma assigned leads count ===\n";
$q = $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID=2291 AND STATUS_SEMANTIC_ID<>'S'");
echo 'Uzma openish leads assigned=' . $q->fetch_assoc()['c'] . "\n";
$q = $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID=2291");
echo 'Uzma all leads assigned=' . $q->fetch_assoc()['c'] . "\n";
