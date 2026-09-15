<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== users ===\n";
$q = $m->query("SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID=2628 OR EMAIL LIKE '%usman.a7group%' OR LOGIN LIKE '%usman%' OR CONCAT(NAME,' ',LAST_NAME) LIKE '%Usman%' ORDER BY ID");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== groups for 2628 ===\n";
$q = $m->query("SELECT ug.GROUP_ID, g.NAME FROM b_user_group ug JOIN b_group g ON g.ID=ug.GROUP_ID WHERE ug.USER_ID=2628");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== UF_DEPARTMENT 2628 ===\n";
$q = $m->query("SELECT UF_DEPARTMENT FROM b_uts_user WHERE VALUE_ID=2628");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== HR departments ===\n";
$q = $m->query("SELECT ID, IBLOCK_ID, IBLOCK_SECTION_ID, NAME, CODE, DEPTH_LEVEL, ACTIVE FROM b_iblock_section WHERE ACTIVE='Y' AND (NAME LIKE '%HR%' OR NAME LIKE '%Human%' OR CODE LIKE '%hr%') ORDER BY IBLOCK_ID, LEFT_MARGIN");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== CRM roles HR ===\n";
$q = $m->query("SELECT ID, NAME FROM b_crm_role WHERE NAME LIKE '%HR%' OR NAME LIKE '%Human%' OR NAME LIKE '%hr%'");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== all CRM roles ===\n";
$q = $m->query("SELECT ID, NAME FROM b_crm_role ORDER BY ID");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== role relations U2628 ===\n";
$q = $m->query("SELECT * FROM b_crm_role_relation WHERE RELATION IN ('U2628')");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== dynamic types HR-ish ===\n";
$chk = $m->query("SHOW TABLES LIKE 'b_crm_dynamic_type'");
if ($chk && $chk->num_rows) {
	$q = $m->query("SELECT ID, ENTITY_TYPE_ID, TITLE, CODE, NAME FROM b_crm_dynamic_type ORDER BY ID");
	if (!$q) {
		$q = $m->query("SELECT * FROM b_crm_dynamic_type LIMIT 40");
	}
	while ($r = $q->fetch_assoc()) {
		$blob = json_encode($r);
		if (stripos($blob, 'hr') !== false || stripos($blob, 'leave') !== false || stripos($blob, 'recruit') !== false) {
			echo $blob . "\n";
		}
	}
	echo "--- all type titles ---\n";
	$q = $m->query("SHOW COLUMNS FROM b_crm_dynamic_type");
	while ($c = $q->fetch_assoc()) {
		echo $c['Field'] . " ";
	}
	echo "\n";
}

echo "=== automated solutions ===\n";
foreach (['b_crm_automated_solution', 'b_intranet_custom_section', 'b_landing'] as $t) {
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
	$sq = $m->query("SELECT * FROM `$t` LIMIT 30");
	while ($r = $sq->fetch_assoc()) {
		$blob = json_encode($r);
		if (stripos($blob, 'hr') !== false || stripos($blob, 'leave') !== false || $t === 'b_crm_automated_solution' || $t === 'b_intranet_custom_section') {
			echo substr($blob, 0, 400) . "\n";
		}
	}
}

echo "=== who is in HR dept / group ===\n";
$q = $m->query("SELECT g.ID, g.NAME, COUNT(ug.USER_ID) c FROM b_group g LEFT JOIN b_user_group ug ON ug.GROUP_ID=g.ID WHERE g.NAME LIKE '%HR%' OR g.NAME LIKE '%Human%' OR g.STRING_ID LIKE '%hr%' GROUP BY g.ID");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== sample users in groups named HR ===\n";
$q = $m->query("SELECT ug.USER_ID, u.NAME, u.LAST_NAME, u.EMAIL, g.ID, g.NAME FROM b_user_group ug JOIN b_group g ON g.ID=ug.GROUP_ID JOIN b_user u ON u.ID=ug.USER_ID WHERE g.NAME LIKE '%HR%' OR g.NAME LIKE '%Human%' OR g.STRING_ID LIKE '%hr%' LIMIT 40");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "DONE\n";
