#!/usr/bin/env php
<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== role 36 ALL perms (first 60) ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=36 ORDER BY ENTITY, PERM_TYPE LIMIT 60");
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";
$q = $m->query("SELECT COUNT(*) c FROM b_crm_role_perms WHERE ROLE_ID=36");
echo "role36 count=" . $q->fetch_assoc()['c'] . "\n";

echo "=== role 6 ALL LEAD-ish ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=6 AND (ENTITY LIKE '%LEAD%' OR ENTITY LIKE '%1042%' OR ENTITY LIKE 'DYNAMIC%') ORDER BY ENTITY LIMIT 40");
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";
$q = $m->query("SELECT COUNT(*) c FROM b_crm_role_perms WHERE ROLE_ID=6");
echo "role6 count=" . $q->fetch_assoc()['c'] . "\n";

echo "=== role 43 relations ===\n";
$q = $m->query("SELECT * FROM b_crm_role_relation WHERE ROLE_ID IN (8,36,43,30,39)");
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== mehnaz canRead LEAD ===\n";
$uid = 2381;
$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
foreach (['LEAD', 'DYNAMIC_1042_C13', 'DYNAMIC_1042_C14'] as $e) {
	$level = $pm->getPermissionLevel($e, 'READ');
	echo "$e READ has=" . ($level->hasPermission()?'Y':'N') . " attrs=" . json_encode($level->getEntityAttributesToCheckInListMode()) . "\n";
}
echo "canReadItems LEAD=" . ($up->entityType()->canReadItems(\CCrmOwnerType::Lead) ? 'Y':'N') . "\n";
echo "canReadItems 1042=" . ($up->entityType()->canReadItems(1042) ? 'Y':'N') . "\n";

// Who has role 8 Sales Agent?
echo "=== who has Sales Agent role 8 ===\n";
$q = $m->query("SELECT RELATION FROM b_crm_role_relation WHERE ROLE_ID=8");
while ($r = $q->fetch_assoc()) echo $r['RELATION'] . "\n";

// Bitrix permission controller for SPA left menu - maybe different
echo "=== type config for 1042 isEnabled / permissions ===\n";
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
echo "factory=" . ($factory ? 'Y' : 'N') . "\n";
if ($factory) {
	echo "isCategoriesEnabled=" . ($factory->isCategoriesEnabled() ? 'Y':'N') . "\n";
	foreach ($factory->getCategories() as $cat) {
		echo "cat id=" . $cat->getId() . " name=" . $cat->getName() . "\n";
	}
}
