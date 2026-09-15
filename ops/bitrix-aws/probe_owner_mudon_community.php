<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== dynamic types 1042/1058/1046/1062 ===\n";
$q = $m->query(
	"SELECT ENTITY_TYPE_ID, CODE, TITLE, TABLE_NAME
	 FROM b_crm_dynamic_type
	 WHERE ENTITY_TYPE_ID IN (1042,1046,1058,1062,5)"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
}

echo "=== relation / parent tables ===\n";
$q = $m->query("SHOW TABLES");
$rel = [];
while ($r = $q->fetch_row()) {
	$n = $r[0];
	if (preg_match('/relation|parent|bind/i', $n) && preg_match('/crm/i', $n)) {
		$rel[] = $n;
		echo $n . "\n";
	}
}

foreach (['b_crm_entity_relation', 'b_crm_item_relation', 'b_crm_relation'] as $t) {
	$chk = $m->query("SHOW TABLES LIKE '$t'");
	if ($chk && $chk->num_rows) {
		$c = $m->query("SHOW COLUMNS FROM $t");
		$cols = [];
		while ($row = $c->fetch_assoc()) {
			$cols[] = $row['Field'];
		}
		echo "$t cols=" . implode(',', $cols) . "\n";
	}
}

\Bitrix\Main\Loader::includeModule('crm');
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$dataClass = $factory ? $factory->getDataClass() : null;
echo "dataClass=" . ($dataClass ?: 'none') . "\n";

if ($dataClass && method_exists($dataClass, 'getMap')) {
	$map = $dataClass::getMap();
	foreach ($map as $k => $v) {
		$name = is_object($v) && method_exists($v, 'getName') ? $v->getName() : (string)$k;
		if (stripos($name, 'PARENT') !== false || stripos($name, '1058') !== false) {
			echo "map $name\n";
		}
	}
}

echo "=== community items table ===\n";
$commTable = null;
$q = $m->query("SELECT TABLE_NAME FROM b_crm_dynamic_type WHERE ENTITY_TYPE_ID=1058");
if ($q && ($r = $q->fetch_assoc())) {
	$commTable = $r['TABLE_NAME'];
}
echo "community_table=$commTable\n";

$mudonIds = [];
if ($commTable) {
	$q = $m->query("SHOW COLUMNS FROM `$commTable`");
	while ($r = $q->fetch_assoc()) {
		if (preg_match('/TITLE|NAME|ID/i', $r['Field'])) {
			echo "comm_col " . $r['Field'] . "\n";
		}
	}
	$q = $m->query(
		"SELECT ID, TITLE FROM `$commTable`
		 WHERE TITLE LIKE '%Mudon%' OR TITLE LIKE '%MUDON%' OR TITLE LIKE '%mudon%'
		 ORDER BY ID"
	);
	echo "=== mudon communities ===\n";
	while ($r = $q->fetch_assoc()) {
		$mudonIds[] = (int)$r['ID'];
		echo $r['ID'] . "\t" . $r['TITLE'] . "\n";
	}
	$allC = (int)$m->query("SELECT COUNT(*) c FROM `$commTable`")->fetch_assoc()['c'];
	echo "community_catalog_total=$allC\n";
}

echo "=== count via factory filter PARENT_ID_1058 ===\n";
if ($factory) {
	$total = $factory->getItemsCount(['CATEGORY_ID' => 14]);
	$with = $factory->getItemsCount([
		'CATEGORY_ID' => 14,
		'!PARENT_ID_1058' => false,
	]);
	$with2 = $factory->getItemsCount([
		'CATEGORY_ID' => 14,
		'>PARENT_ID_1058' => 0,
	]);
	echo "factory_cat14_total=$total\n";
	echo "factory_cat14_community_not_false=$with\n";
	echo "factory_cat14_community_gt0=$with2\n";
	if ($mudonIds) {
		$mudonCount = $factory->getItemsCount([
			'CATEGORY_ID' => 14,
			'PARENT_ID_1058' => $mudonIds,
		]);
		echo "factory_cat14_mudon=$mudonCount\n";
	}
}

echo "=== relation rows src 1042 dst 1058 ===\n";
if (in_array('b_crm_entity_relation', $rel, true) || true) {
	$chk = $m->query("SHOW TABLES LIKE 'b_crm_entity_relation'");
	if ($chk && $chk->num_rows) {
		$q = $m->query(
			"SELECT SRC_ENTITY_TYPE_ID, DST_ENTITY_TYPE_ID, COUNT(*) c
			 FROM b_crm_entity_relation
			 WHERE SRC_ENTITY_TYPE_ID IN (1042,1058) OR DST_ENTITY_TYPE_ID IN (1042,1058)
			 GROUP BY SRC_ENTITY_TYPE_ID, DST_ENTITY_TYPE_ID"
		);
		if ($q) {
			while ($r = $q->fetch_assoc()) {
				echo json_encode($r) . "\n";
			}
		} else {
			echo "relation_query_err " . $m->error . "\n";
			$c = $m->query("SHOW COLUMNS FROM b_crm_entity_relation");
			while ($row = $c->fetch_assoc()) {
				echo "relcol " . $row['Field'] . "\n";
			}
		}
	}
}

echo "DONE\n";
