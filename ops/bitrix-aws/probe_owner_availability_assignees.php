<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
	fwrite(STDERR, "db fail\n");
	exit(2);
}

$total = (int)$m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=14")->fetch_assoc()['c'];
echo "total_category_14=$total\n";

echo "=== sample assigned values ===\n";
$q = $m->query(
	"SELECT ASSIGNED_BY_ID, COUNT(*) c
	 FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	 GROUP BY ASSIGNED_BY_ID
	 ORDER BY c DESC
	 LIMIT 5"
);
while ($r = $q->fetch_assoc()) {
	echo "raw=" . json_encode($r['ASSIGNED_BY_ID']) . "\tc=" . $r['c'] . "\n";
}

echo "=== by assignee ===\n";
$q = $m->query(
	"SELECT
		i.ASSIGNED_BY_ID uid,
		COUNT(*) c,
		u.NAME,
		u.LAST_NAME,
		u.LOGIN,
		u.ACTIVE
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_user u ON u.ID = CAST(i.ASSIGNED_BY_ID AS UNSIGNED)
	 WHERE i.CATEGORY_ID=14
	 GROUP BY i.ASSIGNED_BY_ID, u.NAME, u.LAST_NAME, u.LOGIN, u.ACTIVE
	 ORDER BY c DESC, uid"
);
$sum = 0;
while ($r = $q->fetch_assoc()) {
	$sum += (int)$r['c'];
	$name = trim(($r['NAME'] ?? '') . ' ' . ($r['LAST_NAME'] ?? ''));
	if ($name === '') {
		$name = $r['LOGIN'] ?: 'unassigned';
	}
	$active = ($r['ACTIVE'] ?? '') === 'Y' ? 'Y' : (($r['uid'] === null || $r['uid'] === '' || $r['uid'] === '0') ? '-' : 'N');
	echo $r['c'] . "\t" . $r['uid'] . "\t" . $name . "\tactive=" . $active . "\n";
}
echo "sum_assignees=$sum\n";
echo "DONE\n";
