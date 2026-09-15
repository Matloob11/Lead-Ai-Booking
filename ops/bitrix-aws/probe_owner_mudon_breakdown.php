<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== title mudon by stage cat14 ===\n";
$q = $m->query(
	"SELECT i.STAGE_ID, s.NAME, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_crm_status s ON s.ENTITY_ID='DYNAMIC_1042_STAGE_14' AND s.STATUS_ID=i.STAGE_ID
	 WHERE i.CATEGORY_ID=14 AND i.TITLE LIKE '%Mudon%'
	 GROUP BY i.STAGE_ID, s.NAME
	 ORDER BY c DESC"
);
$titleTotal = 0;
while ($r = $q->fetch_assoc()) {
	$titleTotal += (int)$r['c'];
	echo $r['c'] . "\t" . ($r['NAME'] ?: $r['STAGE_ID']) . "\n";
}
echo "title_mudon_total=$titleTotal\n";

echo "=== any community via relation 1058 <-> 1042 in cat14 ===\n";
$q = $m->query(
	"SELECT COUNT(DISTINCT i.ID) c
	 FROM b_crm_dynamic_items_1042 i
	 JOIN b_crm_entity_relation r
	   ON (
	     (r.SRC_ENTITY_TYPE_ID=1042 AND r.SRC_ENTITY_ID=i.ID AND r.DST_ENTITY_TYPE_ID=1058)
	     OR (r.DST_ENTITY_TYPE_ID=1042 AND r.DST_ENTITY_ID=i.ID AND r.SRC_ENTITY_TYPE_ID=1058)
	   )
	 WHERE i.CATEGORY_ID=14"
);
echo "relation_any_community=" . $q->fetch_assoc()['c'] . "\n";

$mudonIds = '14,18,20,22,24,2411';
$q = $m->query(
	"SELECT COUNT(DISTINCT i.ID) c
	 FROM b_crm_dynamic_items_1042 i
	 JOIN b_crm_entity_relation r
	   ON (
	     (r.SRC_ENTITY_TYPE_ID=1042 AND r.SRC_ENTITY_ID=i.ID AND r.DST_ENTITY_TYPE_ID=1058 AND r.DST_ENTITY_ID IN ($mudonIds))
	     OR (r.DST_ENTITY_TYPE_ID=1042 AND r.DST_ENTITY_ID=i.ID AND r.SRC_ENTITY_TYPE_ID=1058 AND r.SRC_ENTITY_ID IN ($mudonIds))
	   )
	 WHERE i.CATEGORY_ID=14"
);
echo "relation_mudon=" . $q->fetch_assoc()['c'] . "\n";

\Bitrix\Main\Loader::includeModule('crm');
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$items = $factory->getItems([
	'select' => ['ID', 'TITLE', 'STAGE_ID', 'PARENT_ID_1058'],
	'filter' => [
		'CATEGORY_ID' => 14,
		'>PARENT_ID_1058' => 0,
	],
	'limit' => 500,
]);
$byComm = [];
foreach ($items as $item) {
	$cid = (int)$item->get('PARENT_ID_1058');
	$byComm[$cid] = ($byComm[$cid] ?? 0) + 1;
}
arsort($byComm);
$ids = array_keys($byComm);
$idIn = $ids ? implode(',', $ids) : '0';
$names = [];
$q = $m->query("SELECT ID, TITLE FROM b_crm_dynamic_items_1058 WHERE ID IN ($idIn)");
while ($r = $q->fetch_assoc()) {
	$names[(int)$r['ID']] = $r['TITLE'];
}
echo "=== community field values in cat14 ===\n";
foreach ($byComm as $cid => $c) {
	echo $c . "\t" . $cid . "\t" . ($names[$cid] ?? '?') . "\n";
}

echo "=== title mudon AND community field set ===\n";
$both = $factory->getItemsCount([
	'CATEGORY_ID' => 14,
	'>PARENT_ID_1058' => 0,
	'%TITLE' => 'Mudon',
]);
echo "title_and_field=$both\n";
echo "DONE\n";
