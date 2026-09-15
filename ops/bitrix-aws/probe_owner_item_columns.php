<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== all columns b_crm_dynamic_items_1042 ===\n";
$q = $m->query("SHOW COLUMNS FROM b_crm_dynamic_items_1042");
while ($r = $q->fetch_assoc()) {
	echo $r['Field'] . "\t" . $r['Type'] . "\n";
}

echo "=== type 21 / 22 names ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_crm_dynamic_type%'");
while ($r = $q->fetch_row()) {
	echo $r[0] . "\n";
}
foreach (['b_crm_dynamic_type', 'b_crm_entity'] as $t) {
	$chk = $m->query("SHOW TABLES LIKE '$t'");
	if ($chk && $chk->num_rows) {
		$q = $m->query("SELECT * FROM $t LIMIT 1");
		$fields = $q ? array_keys($q->fetch_assoc() ?: []) : [];
		echo "$t cols=" . implode(',', $fields) . "\n";
	}
}

echo "=== UF entities all CRM_* counts ===\n";
$q = $m->query("SELECT ENTITY_ID, COUNT(*) c FROM b_user_field WHERE ENTITY_ID LIKE 'CRM_%' GROUP BY ENTITY_ID ORDER BY ENTITY_ID");
while ($r = $q->fetch_assoc()) {
	echo $r['ENTITY_ID'] . "\t" . $r['c'] . "\n";
}

echo "=== mudon titles sample cat14 ===\n";
$q = $m->query(
	"SELECT ID, TITLE, STAGE_ID FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND TITLE LIKE '%Mudon%'
	 ORDER BY ID DESC LIMIT 15"
);
while ($r = $q->fetch_assoc()) {
	echo $r['ID'] . "\t" . $r['STAGE_ID'] . "\t" . $r['TITLE'] . "\n";
}

echo "=== factory fields 1042 ===\n";
\Bitrix\Main\Loader::includeModule('crm');
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
if ($factory) {
	foreach ($factory->getFieldsInfo() as $name => $info) {
		$title = $info['TITLE'] ?? '';
		if (stripos($name, 'COMMUNIT') !== false || stripos($title, 'communit') !== false || stripos($title, 'mudon') !== false || stripos($name, 'PROJECT') !== false || stripos($title, 'project') !== false) {
			echo $name . "\t" . $title . "\t" . ($info['TYPE'] ?? '') . "\n";
		}
	}
} else {
	echo "no factory\n";
}
echo "DONE\n";
