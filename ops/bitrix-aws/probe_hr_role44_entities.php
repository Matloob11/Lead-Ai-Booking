<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== role 44 entities ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, LEFT(SETTINGS,120) S FROM b_crm_role_perms WHERE ROLE_ID=44 ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== role 45 entities ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, LEFT(SETTINGS,120) S FROM b_crm_role_perms WHERE ROLE_ID=45 ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== role 3 HR entities only ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, LEFT(SETTINGS,80) S FROM b_crm_role_perms WHERE ROLE_ID=3 AND (ENTITY LIKE '%1156%' OR ENTITY LIKE '%1160%' OR ENTITY LIKE '%1168%' OR ENTITY LIKE '%1172%' OR ENTITY LIKE '%1038%') ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== categories for 1156/1160/1168/1172 ===\n";
$q = $m->query("SELECT ID, NAME, ENTITY_TYPE_ID, IS_DEFAULT FROM b_crm_item_category WHERE ENTITY_TYPE_ID IN (1156,1160,1168,1172) ORDER BY ENTITY_TYPE_ID, ID");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "DONE\n";
