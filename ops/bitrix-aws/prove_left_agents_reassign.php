<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$leavers = '7,2378,2296,2293,2294,15,2292,2300,2218';
$old = 'DT1042_14:UC_YCY8JG';
$q = $m->query(
	"SELECT i.ASSIGNED_BY_ID, u.NAME, u.LAST_NAME, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_user u ON u.ID=CAST(i.ASSIGNED_BY_ID AS UNSIGNED)
	 WHERE i.CATEGORY_ID=14 AND i.STAGE_ID <> '$old'
	   AND i.ASSIGNED_BY_ID IN ($leavers)
	 GROUP BY i.ASSIGNED_BY_ID, u.NAME, u.LAST_NAME
	 ORDER BY c DESC"
);
echo "=== leavers still hold (except old) ===\n";
while ($r = $q->fetch_assoc()) {
	echo $r['c'] . "\t" . trim($r['NAME'] . ' ' . $r['LAST_NAME']) . "\n";
}

$got = [2291, 2434, 2344, 2429, 2302, 2298, 2379, 2380, 2376];
$q = $m->query(
	"SELECT i.ASSIGNED_BY_ID, u.NAME, u.LAST_NAME, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_user u ON u.ID=CAST(i.ASSIGNED_BY_ID AS UNSIGNED)
	 WHERE i.CATEGORY_ID=14 AND i.STAGE_ID <> '$old'
	   AND i.ASSIGNED_BY_ID IN (" . implode(',', $got) . ")
	 GROUP BY i.ASSIGNED_BY_ID, u.NAME, u.LAST_NAME
	 ORDER BY c DESC"
);
echo "=== receivers now hold ===\n";
while ($r = $q->fetch_assoc()) {
	echo $r['c'] . "\t" . trim($r['NAME'] . ' ' . $r['LAST_NAME']) . "\n";
}
echo "DONE\n";
