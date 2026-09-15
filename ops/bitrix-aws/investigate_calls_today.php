<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== last 40 calls today ===\n";
$q = $m->query("SELECT ID,CALL_START_DATE,PORTAL_USER_ID,PORTAL_NUMBER,PHONE_NUMBER,CALL_DURATION,CALL_STATUS,CALL_FAILED_CODE,CALL_FAILED_REASON,REST_APP_ID,REST_APP_NAME,CRM_ENTITY_TYPE,CRM_ENTITY_ID,INCOMING FROM b_voximplant_statistic WHERE CALL_START_DATE >= '2026-08-31 00:00:00' ORDER BY ID DESC LIMIT 40");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
}

echo "=== sip+config (no password) ===\n";
$q = $m->query("SELECT s.ID,s.CONFIG_ID,s.TYPE,s.REG_ID,s.SERVER,s.LOGIN,s.REGISTRATION_STATUS_CODE,s.REGISTRATION_ERROR_MESSAGE,c.PORTAL_MODE,c.PHONE_NAME,c.SEARCH_ID FROM b_voximplant_sip s LEFT JOIN b_voximplant_config c ON c.ID=s.CONFIG_ID");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
}

echo "=== fail code counts last 7d ===\n";
$q = $m->query("SELECT CALL_FAILED_CODE, CALL_FAILED_REASON, PORTAL_NUMBER, REST_APP_NAME, COUNT(*) c FROM b_voximplant_statistic WHERE CALL_START_DATE >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND CALL_STATUS='0' GROUP BY CALL_FAILED_CODE, CALL_FAILED_REASON, PORTAL_NUMBER, REST_APP_NAME ORDER BY c DESC LIMIT 30");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
}

echo "=== recent Zadarma app77 / reg68829 ===\n";
$q = $m->query("SELECT ID,CALL_START_DATE,PORTAL_NUMBER,PHONE_NUMBER,CALL_DURATION,CALL_FAILED_CODE,CALL_FAILED_REASON,REST_APP_ID,REST_APP_NAME,PORTAL_USER_ID FROM b_voximplant_statistic WHERE PORTAL_NUMBER IN ('reg68829','REST_APP:77') OR REST_APP_ID=77 ORDER BY ID DESC LIMIT 20");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
}

echo "DONE\n";
