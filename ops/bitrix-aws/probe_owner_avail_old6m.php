<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== now / cutoff ===\n";
$now = $m->query("SELECT NOW() n, DATE_SUB(NOW(), INTERVAL 6 MONTH) cutoff")->fetch_assoc();
echo json_encode($now) . "\n";

echo "=== stages cat 14 ===\n";
$q = $m->query(
	"SELECT STATUS_ID, NAME, SORT, SEMANTICS
	 FROM b_crm_status
	 WHERE ENTITY_ID='DYNAMIC_1042_STAGE_14'
	 ORDER BY SORT"
);
$stages = [];
$oldStage = null;
while ($r = $q->fetch_assoc()) {
	$stages[$r['STATUS_ID']] = $r;
	echo $r['STATUS_ID'] . "\t" . $r['NAME'] . "\tsort=" . $r['SORT'] . "\tsem=" . $r['SEMANTICS'] . "\n";
	if (stripos($r['NAME'], 'old') !== false && stripos($r['NAME'], '6') !== false) {
		$oldStage = $r['STATUS_ID'];
	}
}
echo "old_stage=" . ($oldStage ?: 'MISSING') . "\n";

echo "=== all cat14 vs created>6m vs activity>6m ===\n";
$q = $m->query(
	"SELECT
		COUNT(*) total,
		SUM(CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)) created_old,
		SUM(LAST_ACTIVITY_TIME IS NOT NULL AND LAST_ACTIVITY_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)) activity_old,
		SUM(UPDATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)) updated_old,
		SUM(MOVED_TIME IS NOT NULL AND MOVED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)) moved_old
	 FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14"
);
echo json_encode($q->fetch_assoc()) . "\n";

echo "=== created_old by stage ===\n";
$q = $m->query(
	"SELECT i.STAGE_ID, s.NAME, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_crm_status s ON s.ENTITY_ID='DYNAMIC_1042_STAGE_14' AND s.STATUS_ID=i.STAGE_ID
	 WHERE i.CATEGORY_ID=14
	   AND i.CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	 GROUP BY i.STAGE_ID, s.NAME
	 ORDER BY c DESC"
);
while ($r = $q->fetch_assoc()) {
	echo $r['c'] . "\t" . ($r['NAME'] ?: $r['STAGE_ID']) . "\t" . $r['STAGE_ID'] . "\n";
}

echo "=== sample created_old ===\n";
$q = $m->query(
	"SELECT ID, TITLE, STAGE_ID, CREATED_TIME, LAST_ACTIVITY_TIME, ASSIGNED_BY_ID
	 FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	 ORDER BY CREATED_TIME ASC LIMIT 5"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
}

echo "=== newest created_old ===\n";
$q = $m->query(
	"SELECT ID, TITLE, STAGE_ID, CREATED_TIME
	 FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	 ORDER BY CREATED_TIME DESC LIMIT 3"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
}
echo "DONE\n";
