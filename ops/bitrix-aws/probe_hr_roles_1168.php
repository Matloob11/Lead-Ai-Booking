<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== role relations 42/44/45 ===\n";
$q = $m->query("SELECT * FROM b_crm_role_relation WHERE ROLE_ID IN (42,44,45) ORDER BY ROLE_ID, RELATION");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== perms 42/44/45 on 1168/1160/HR ===\n";
$q = $m->query("SELECT ROLE_ID, ENTITY, FIELD, PERM_TYPE, ATTR, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID IN (42,44,45) AND (ENTITY LIKE '%1168%' OR ENTITY LIKE '%1160%' OR ENTITY LIKE '%HR%' OR ENTITY LIKE '%1148%') ORDER BY ROLE_ID, ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== all entities on role 44 ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, LEFT(SETTINGS,80) S FROM b_crm_role_perms WHERE ROLE_ID=44 ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== all entities on role 42 ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, LEFT(SETTINGS,80) S FROM b_crm_role_perms WHERE ROLE_ID=42 ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== all entities on role 45 ===\n";
$q = $m->query("SELECT ENTITY, PERM_TYPE, ATTR, LEFT(SETTINGS,80) S FROM b_crm_role_perms WHERE ROLE_ID=45 ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== who has 1168 READ X or ALL ===\n";
$q = $m->query("SELECT ROLE_ID, ENTITY, PERM_TYPE, ATTR, LEFT(SETTINGS,100) S FROM b_crm_role_perms WHERE ENTITY LIKE '%1168%' ORDER BY ROLE_ID, ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== known HR user 2319 groups + roles + dept ===\n";
foreach ([2319, 2450, 2287, 1] as $uid) {
	$u = $m->query("SELECT ID, NAME, LAST_NAME, EMAIL, ACTIVE FROM b_user WHERE ID=$uid")->fetch_assoc();
	echo "USER " . json_encode($u) . "\n";
	$g = $m->query("SELECT g.ID, g.NAME FROM b_user_group ug JOIN b_group g ON g.ID=ug.GROUP_ID WHERE ug.USER_ID=$uid");
	while ($r = $g->fetch_assoc()) {
		echo "  G " . json_encode($r) . "\n";
	}
	$d = $m->query("SELECT UF_DEPARTMENT FROM b_uts_user WHERE VALUE_ID=$uid")->fetch_assoc();
	echo "  DEPT " . json_encode($d) . "\n";
	$rel = $m->query("SELECT * FROM b_crm_role_relation WHERE RELATION='U$uid'");
	while ($r = $rel->fetch_assoc()) {
		echo "  ROLE " . json_encode($r) . "\n";
	}
}

echo "=== custom section pages for HR ===\n";
foreach (['b_intranet_custom_section_page', 'b_crm_automated_solution_entity'] as $t) {
	$chk = $m->query("SHOW TABLES LIKE '$t'");
	if (!$chk || !$chk->num_rows) {
		echo "missing $t\n";
		continue;
	}
	echo "TABLE $t\n";
	$q = $m->query("SHOW COLUMNS FROM `$t`");
	$cols = [];
	while ($c = $q->fetch_assoc()) {
		$cols[] = $c['Field'];
	}
	echo implode(',', $cols) . "\n";
	$sq = $m->query("SELECT * FROM `$t`");
	while ($r = $sq->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
}

echo "=== left menu / sitemap hr_request ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_intranet%'");
while ($r = $q->fetch_row()) {
	echo $r[0] . "\n";
}

echo "DONE\n";
