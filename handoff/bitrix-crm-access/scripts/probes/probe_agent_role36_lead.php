#!/usr/bin/env php
<?php
/**
 * Compare Agent (36) / Employee (6) LEAD vs Owner Data perms.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

foreach ([6, 8, 36, 43, 54] as $rid) {
	echo "==== ROLE $rid ====\n";
	$q = $m->query(
		"SELECT ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS
		 FROM b_crm_role_perms
		 WHERE ROLE_ID=$rid
		   AND (ENTITY='LEAD' OR ENTITY LIKE 'DYNAMIC_1042%' OR ENTITY LIKE 'DYNAMIC_%')
		 ORDER BY ENTITY, PERM_TYPE, FIELD"
	);
	$n = 0;
	while ($r = $q->fetch_assoc()) {
		$n++;
		if (str_starts_with($r['ENTITY'], 'DYNAMIC_') && !str_contains($r['ENTITY'], '1042') && !str_starts_with($r['ENTITY'], 'LEAD')) {
			continue; // skip other SPAs for brevity unless LEAD/1042
		}
		if ($r['ENTITY'] === 'LEAD' || str_contains($r['ENTITY'], '1042')) {
			echo json_encode($r) . "\n";
		}
	}
	echo "(shown LEAD+1042 only; total rows for role filter query walked)\n\n";
}

// How does Bitrix set ATTR A vs SETTINGS?
echo "=== sample Agent LEAD all perm types ===\n";
$q = $m->query("SELECT * FROM b_crm_role_perms WHERE ROLE_ID=36 AND ENTITY='LEAD' ORDER BY PERM_TYPE, FIELD");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "\n=== sample Sales Agent (8) LEAD ===\n";
$q = $m->query("SELECT * FROM b_crm_role_perms WHERE ROLE_ID=8 AND ENTITY='LEAD' ORDER BY PERM_TYPE, FIELD LIMIT 40");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "\n=== group G11 / G12 members count ===\n";
$q = $m->query("SELECT GROUP_ID, COUNT(*) c FROM b_user_group WHERE GROUP_ID IN (11,12) GROUP BY GROUP_ID");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}
