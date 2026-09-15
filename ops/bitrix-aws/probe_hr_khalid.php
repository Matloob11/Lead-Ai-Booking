<?php
/**
 * Find Khalid / furqan.a7group@gmail.com and compare HR access
 * against Iraj (2243), Amna (2319), Usman (2628).
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== users matching furqan / khalid / 26320 ===\n";
$q = $m->query(
	"SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, ACTIVE FROM b_user
	 WHERE ID=26320
	    OR EMAIL LIKE '%furqan.a7group%'
	    OR LOGIN LIKE '%furqan%'
	    OR CONCAT(NAME,' ',LAST_NAME) LIKE '%Khalid%'
	 ORDER BY ID"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

function dumpUser($m, $uid) {
	$u = $m->query("SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID=" . (int) $uid)->fetch_assoc();
	echo "USER " . json_encode($u) . "\n";
	if (!$u) {
		return;
	}
	$g = $m->query("SELECT g.ID, g.NAME FROM b_user_group ug JOIN b_group g ON g.ID=ug.GROUP_ID WHERE ug.USER_ID=" . (int) $uid);
	while ($r = $g->fetch_assoc()) {
		echo "  G " . json_encode($r) . "\n";
	}
	$d = $m->query("SELECT UF_DEPARTMENT FROM b_uts_user WHERE VALUE_ID=" . (int) $uid)->fetch_assoc();
	echo "  DEPT " . json_encode($d) . "\n";
	$rel = $m->query("SELECT rr.ROLE_ID, r.NAME FROM b_crm_role_relation rr JOIN b_crm_role r ON r.ID=rr.ROLE_ID WHERE rr.RELATION='U" . (int) $uid . "'");
	while ($r = $rel->fetch_assoc()) {
		echo "  ROLE " . json_encode($r) . "\n";
	}
}

echo "=== templates Iraj 2243 / Amna 2319 / Usman 2628 ===\n";
foreach ([2243, 2319, 2628, 26320] as $uid) {
	dumpUser($m, $uid);
}

echo "=== CRM entity read for those users ===\n";
foreach ([2243, 2319, 2628, 26320] as $uid) {
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$et = $up->entityType();
	echo "uid=$uid";
	foreach ([1168, 1160, 1156, 1172, 1148] as $type) {
		$read = $et->canReadItems($type) ? 'Y' : 'N';
		echo "  $type=$read";
	}
	echo "\n";
}

echo "=== dashboard-ish tables ===\n";
foreach (['b_biconnector_dashboard', 'b_biconnector_dashboard_user', 'b_biconnector_superset_dashboard', 'b_intranet_custom_section', 'b_landing'] as $t) {
	$chk = $m->query("SHOW TABLES LIKE '$t'");
	echo ($chk && $chk->num_rows ? "HAS " : "no  ") . $t . "\n";
}

$chk = $m->query("SHOW TABLES LIKE 'b_biconnector%'");
while ($r = $chk->fetch_row()) {
	echo "bicon " . $r[0] . "\n";
}

echo "=== custom sections ===\n";
$chk = $m->query("SHOW TABLES LIKE 'b_intranet_custom_section'");
if ($chk && $chk->num_rows) {
	$q = $m->query("SELECT * FROM b_intranet_custom_section");
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
}

echo "=== automated solutions ===\n";
$chk = $m->query("SHOW TABLES LIKE 'b_crm_automated_solution'");
if ($chk && $chk->num_rows) {
	$q = $m->query("SELECT * FROM b_crm_automated_solution");
	while ($r = $q->fetch_assoc()) {
		echo substr(json_encode($r), 0, 500) . "\n";
	}
}

echo "DONE\n";
