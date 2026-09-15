<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== live ONEXTERNALCALL* ===\n";
$q = $m->query(
	"SELECT e.ID,e.EVENT_NAME,e.EVENT_HANDLER,e.APP_ID,a.CODE,a.APP_NAME,a.ACTIVE,a.STATUS
	 FROM b_rest_event e
	 LEFT JOIN b_rest_app a ON a.ID=e.APP_ID
	 WHERE e.EVENT_NAME IN ('ONEXTERNALCALLSTART','ONEXTERNALCALLBACKSTART')
	    OR e.EVENT_HANDLER LIKE '%voiso%'
	    OR e.EVENT_HANDLER LIKE '%ams04%'
	    OR e.EVENT_HANDLER LIKE '%zadarma%'
	 ORDER BY e.ID"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== apps voiso/zadarma/cloud ===\n";
$q = $m->query(
	"SELECT ID,CODE,ACTIVE,STATUS,APP_NAME,CLIENT_ID
	 FROM b_rest_app
	 WHERE LOWER(APP_NAME) LIKE '%voiso%'
	    OR LOWER(APP_NAME) LIKE '%zadarma%'
	    OR LOWER(CODE) LIKE '%voiso%'
	    OR LOWER(CODE) LIKE '%zadarma%'
	    OR LOWER(APP_NAME) LIKE '%cloud%'
	    OR LOWER(APP_NAME) LIKE '%a7%'
	 ORDER BY ID"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== voiso backup ===\n";
$chk = $m->query("SHOW TABLES LIKE 'a7_rest_event_voiso_backup'");
if ($chk && $chk->num_rows) {
	$q = $m->query('SELECT ID,EVENT_NAME,EVENT_HANDLER,APP_ID FROM a7_rest_event_voiso_backup');
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
} else {
	echo "no backup table\n";
}

echo "=== owner call js snippet ===\n";
$js = @file_get_contents('/home/bitrix/www/bitrix/js/a7_owner_data_call.js');
echo 'size=' . strlen((string)$js) . "\n";
if (preg_match_all('/dialVia\\w+|Voiso|Zadarma|phoneTo|Call with/i', (string)$js, $mm)) {
	echo implode(',', array_unique($mm[0])) . "\n";
}
