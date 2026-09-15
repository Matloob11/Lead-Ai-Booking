<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$work = [
	'DT1042_14:NEW',
	'DT1042_14:UC_73SP7H',
	'DT1042_14:PREPARATION',
	'DT1042_14:UC_G0PCBL',
	'DT1042_14:UC_39DSJP',
	'DT1042_14:UC_76AZKL',
	'DT1042_14:UC_PKIJWV',
];
$in = "'" . implode("','", $work) . "'";
$q = $m->query(
	"SELECT i.STAGE_ID, s.NAME, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_crm_status s ON s.ENTITY_ID='DYNAMIC_1042_STAGE_14' AND s.STATUS_ID=i.STAGE_ID
	 WHERE i.CATEGORY_ID=14 AND i.STAGE_ID IN ($in)
	 GROUP BY i.STAGE_ID, s.NAME
	 ORDER BY c DESC"
);
$total = 0;
while ($r = $q->fetch_assoc()) {
	$total += (int)$r['c'];
	echo $r['c'] . "\t" . $r['NAME'] . "\n";
}
echo "actionable_total=$total\n";
