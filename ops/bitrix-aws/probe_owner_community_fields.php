<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== UF entities containing 1042 ===\n";
$q = $m->query(
	"SELECT DISTINCT ENTITY_ID, COUNT(*) c
	 FROM b_user_field
	 WHERE ENTITY_ID LIKE '%1042%'
	 GROUP BY ENTITY_ID"
);
while ($r = $q->fetch_assoc()) {
	echo $r['ENTITY_ID'] . "\t" . $r['c'] . "\n";
}

echo "=== any UF label community ===\n";
$q = $m->query(
	"SELECT f.ENTITY_ID, f.FIELD_NAME, f.USER_TYPE_ID, l.EDIT_FORM_LABEL
	 FROM b_user_field f
	 LEFT JOIN b_user_field_lang l ON l.USER_FIELD_ID=f.ID AND l.LANGUAGE_ID='en'
	 WHERE l.EDIT_FORM_LABEL LIKE '%Communit%'
	    OR l.EDIT_FORM_LABEL LIKE '%Mudon%'
	    OR f.FIELD_NAME LIKE '%COMMUNIT%'
	 ORDER BY f.ENTITY_ID, f.FIELD_NAME"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
}

echo "=== item 1042 columns matching community/title ===\n";
$q = $m->query("SHOW COLUMNS FROM b_crm_dynamic_items_1042");
$cols = [];
while ($r = $q->fetch_assoc()) {
	$cols[] = $r['Field'];
	$low = strtolower($r['Field']);
	if (preg_match('/communit|title|name|project|area|location|develop/i', $r['Field'])) {
		echo $r['Field'] . "\t" . $r['Type'] . "\n";
	}
}

echo "=== title mudon in cat 14 ===\n";
$q = $m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND (TITLE LIKE '%Mudon%' OR TITLE LIKE '%MUDON%' OR TITLE LIKE '%mudon%')"
);
echo "title_mudon=" . $q->fetch_assoc()['c'] . "\n";

$q = $m->query(
	"SELECT ID, TITLE FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	 ORDER BY ID DESC LIMIT 8"
);
echo "=== sample titles cat14 ===\n";
while ($r = $q->fetch_assoc()) {
	echo $r['ID'] . "\t" . $r['TITLE'] . "\n";
}

echo "=== uts tables like %1042% or %crm% ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_uts%'");
while ($r = $q->fetch_row()) {
	if (stripos($r[0], '1042') !== false || stripos($r[0], 'crm') !== false) {
		echo $r[0] . "\n";
	}
}

echo "DONE\n";
