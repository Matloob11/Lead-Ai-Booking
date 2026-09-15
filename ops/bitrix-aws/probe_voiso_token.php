<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== tables rest* ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_rest%'");
while ($r = $q->fetch_row()) {
	echo $r[0] . "\n";
}

echo "=== backup full row ===\n";
$q = $m->query('SELECT * FROM a7_rest_event_voiso_backup');
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== event cols ===\n";
$q = $m->query('SHOW COLUMNS FROM b_rest_event');
while ($r = $q->fetch_assoc()) {
	echo $r['Field'] . ' ';
}
echo "\n";

echo "=== any voiso in options/settings ===\n";
$q = $m->query(
	"SELECT NAME, LEFT(VALUE,200) V FROM b_option
	 WHERE MODULE_ID LIKE '%rest%' AND (NAME LIKE '%voiso%' OR VALUE LIKE '%voiso%' OR VALUE LIKE '%ams04%')
	 LIMIT 20"
);
if ($q) {
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
}

// Outbound webhook apps often have APP_ID null and APPLICATION_TOKEN in EVENT
$q = $m->query("SHOW COLUMNS FROM b_rest_event LIKE '%TOKEN%'");
while ($r = $q->fetch_assoc()) {
	echo 'tokencol ' . json_encode($r) . "\n";
}

echo "=== sample live event row structure ===\n";
$q = $m->query('SELECT * FROM b_rest_event WHERE ID=899');
echo json_encode($q->fetch_assoc()) . "\n";

echo "=== a7_3cx handler actions ===\n";
$php = file_get_contents('/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php');
if (preg_match_all("/action\\s*===\\s*'([^']+)'/", $php, $mm)) {
	echo implode("\n", array_unique($mm[1])) . "\n";
}
if (str_contains($php, 'voiso') || str_contains($php, 'Voiso')) {
	echo "HAS VOISO STRING\n";
}
