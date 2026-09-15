<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

const TARGET = 2632;

echo "=== target 2632 ===\n";
$u = $m->query("SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID=" . TARGET)->fetch_assoc();
echo json_encode($u) . "\n";
$g = $m->query("SELECT g.ID, g.NAME FROM b_user_group ug JOIN b_group g ON g.ID=ug.GROUP_ID WHERE ug.USER_ID=" . TARGET);
while ($r = $g->fetch_assoc()) {
	echo "G " . json_encode($r) . "\n";
}
$d = $m->query("SELECT UF_DEPARTMENT FROM b_uts_user WHERE VALUE_ID=" . TARGET)->fetch_assoc();
echo "DEPT " . json_encode($d) . "\n";
$rel = $m->query("SELECT rr.ROLE_ID, r.NAME FROM b_crm_role_relation rr JOIN b_crm_role r ON r.ID=rr.ROLE_ID WHERE rr.RELATION='U" . TARGET . "' OR rr.RELATION='G9'");
while ($r = $rel->fetch_assoc()) {
	echo "ROLE " . json_encode($r) . "\n";
}

echo "=== HR solution entities ===\n";
foreach (['b_crm_automated_solution_entity', 'b_intranet_custom_section_page'] as $t) {
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

echo "=== dynamic types ===\n";
$chk = $m->query("SHOW TABLES LIKE 'b_crm_dynamic_type'");
if ($chk && $chk->num_rows) {
	$q = $m->query("SHOW COLUMNS FROM b_crm_dynamic_type");
	$cols = [];
	while ($c = $q->fetch_assoc()) {
		$cols[] = $c['Field'];
	}
	echo implode(',', $cols) . "\n";
	$titleCol = in_array('TITLE', $cols, true) ? 'TITLE' : (in_array('NAME', $cols, true) ? 'NAME' : $cols[0]);
	$q = $m->query("SELECT * FROM b_crm_dynamic_type");
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
}

echo "=== biconnector permission / roles ===\n";
$q = $m->query("SHOW COLUMNS FROM b_biconnector_role");
while ($c = $q->fetch_assoc()) {
	echo $c['Field'] . ' ';
}
echo "\n";
$q = $m->query("SELECT * FROM b_biconnector_role");
while ($r = $q->fetch_assoc()) {
	echo "ROLE " . json_encode($r) . "\n";
}
$q = $m->query("SELECT * FROM b_biconnector_role_relation");
while ($r = $q->fetch_assoc()) {
	echo "REL " . json_encode($r) . "\n";
}
$q = $m->query("SELECT * FROM b_biconnector_permission LIMIT 80");
while ($r = $q->fetch_assoc()) {
	echo "PERM " . json_encode($r) . "\n";
}

echo "=== dashboard user shares for HR people ===\n";
$q = $m->query("SHOW COLUMNS FROM b_biconnector_dashboard_user");
while ($c = $q->fetch_assoc()) {
	echo $c['Field'] . ' ';
}
echo "\n";
$q = $m->query("SELECT * FROM b_biconnector_dashboard_user WHERE USER_ID IN (2243,2319,2628,2632) OR USER_ID=0 LIMIT 80");
if ($q) {
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
}

echo "=== dashboards ===\n";
$q = $m->query("SHOW COLUMNS FROM b_biconnector_dashboard");
$cols = [];
while ($c = $q->fetch_assoc()) {
	$cols[] = $c['Field'];
}
echo implode(',', $cols) . "\n";
$q = $m->query("SELECT * FROM b_biconnector_dashboard LIMIT 40");
while ($r = $q->fetch_assoc()) {
	echo substr(json_encode($r), 0, 400) . "\n";
}

echo "=== superset dashboards ===\n";
$q = $m->query("SHOW COLUMNS FROM b_biconnector_superset_dashboard");
$cols = [];
while ($c = $q->fetch_assoc()) {
	$cols[] = $c['Field'];
}
echo implode(',', $cols) . "\n";
$q = $m->query("SELECT ID, TITLE, STATUS, TYPE, APP_ID, OWNER_ID FROM b_biconnector_superset_dashboard LIMIT 60");
if (!$q) {
	$q = $m->query("SELECT * FROM b_biconnector_superset_dashboard LIMIT 20");
}
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== superset shares for 2319/2628/2632 ===\n";
$q = $m->query("SHOW COLUMNS FROM b_biconnector_superset_dashboard_share");
while ($c = $q->fetch_assoc()) {
	echo $c['Field'] . ' ';
}
echo "\n";
$q = $m->query("SELECT * FROM b_biconnector_superset_dashboard_share LIMIT 80");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== dashboard groups / scope ===\n";
foreach (['b_biconnector_superset_dashboard_group', 'b_biconnector_superset_dashboard_group_binding', 'b_biconnector_superset_dashboard_group_scope', 'b_biconnector_superset_scope'] as $t) {
	echo "TABLE $t\n";
	$q = $m->query("SELECT * FROM `$t` LIMIT 40");
	if (!$q) {
		echo $m->error . "\n";
		continue;
	}
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
}

echo "DONE\n";
