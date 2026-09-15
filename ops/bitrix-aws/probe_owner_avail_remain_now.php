<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$old = 'DT1042_14:UC_YCY8JG';
$total = (int)$m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=14")->fetch_assoc()['c'];
$inOld = (int)$m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=14 AND STAGE_ID='$old'")->fetch_assoc()['c'];
echo "total_cat14=$total\n";
echo "old_stage=$inOld\n";
echo "remain_except_old=" . ($total - $inOld) . "\n";
$q = $m->query(
	"SELECT s.NAME, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_crm_status s ON s.ENTITY_ID='DYNAMIC_1042_STAGE_14' AND s.STATUS_ID=i.STAGE_ID
	 WHERE i.CATEGORY_ID=14 AND i.STAGE_ID <> '$old'
	 GROUP BY s.NAME ORDER BY c DESC"
);
while ($r = $q->fetch_assoc()) {
	echo $r['c'] . "\t" . $r['NAME'] . "\n";
}
