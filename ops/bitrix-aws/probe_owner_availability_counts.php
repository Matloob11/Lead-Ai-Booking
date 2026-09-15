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

echo "=== owner data categories ===\n";
$q = $m->query(
	"SELECT ID, NAME, SORT, IS_DEFAULT
	 FROM b_crm_item_category
	 WHERE ENTITY_TYPE_ID=1042
	 ORDER BY SORT, ID"
);
if ($q) {
	while ($r = $q->fetch_assoc()) {
		echo $r['ID'] . "\t" . $r['NAME'] . "\tdefault=" . $r['IS_DEFAULT'] . "\n";
	}
}

echo "=== stages category 14 ===\n";
$q = $m->query(
	"SELECT STATUS_ID, NAME, SORT, SEMANTICS
	 FROM b_crm_status
	 WHERE ENTITY_ID='DYNAMIC_1042_STAGE_14'
	 ORDER BY SORT"
);
$stages = [];
while ($r = $q->fetch_assoc()) {
	$stages[$r['STATUS_ID']] = $r;
	echo $r['STATUS_ID'] . "\t" . $r['NAME'] . "\tsort=" . $r['SORT'] . "\n";
}

echo "=== counts category 14 ===\n";
$total = 0;
$q = $m->query(
	"SELECT STAGE_ID, COUNT(*) c
	 FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	 GROUP BY STAGE_ID"
);
$byStage = [];
while ($r = $q->fetch_assoc()) {
	$byStage[$r['STAGE_ID']] = (int)$r['c'];
	$total += (int)$r['c'];
}

$availSum = 0;
foreach ($stages as $sid => $meta) {
	$c = $byStage[$sid] ?? 0;
	$name = $meta['NAME'];
	echo $sid . "\t" . $name . "\t" . $c . "\n";
	if (stripos($name, 'availab') !== false) {
		$availSum += $c;
	}
}
foreach ($byStage as $sid => $c) {
	if (!isset($stages[$sid])) {
		echo $sid . "\tUNKNOWN\t" . $c . "\n";
	}
}

$allCat = (int)$m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=14")->fetch_assoc()['c'];
echo "total_category_14=$allCat\n";
echo "sum_stages_named_availability=$availSum\n";

$allSpa = (int)$m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042")->fetch_assoc()['c'];
echo "total_owner_data_all_categories=$allSpa\n";
echo "DONE\n";
