<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
    fwrite(STDERR, $m->connect_error . PHP_EOL);
    exit(1);
}

function rows(mysqli $m, string $sql): void
{
    $q = $m->query($sql);
    if (!$q) {
        echo "SQL ERR: " . $m->error . "\n$sql\n";
        return;
    }
    while ($r = $q->fetch_assoc()) {
        echo implode("\t", array_map(static function ($v) {
            return is_null($v) ? 'NULL' : str_replace(["\n", "\t"], [' ', ' '], (string)$v);
        }, $r)) . "\n";
    }
}

echo "=== ONEXTERNAL handlers ===\n";
rows($m, "SELECT ID, EVENT_NAME, APP_ID, LEFT(EVENT_HANDLER,160) H
FROM b_rest_event
WHERE EVENT_NAME LIKE '%EXTERNALCALL%' OR EVENT_HANDLER LIKE '%zadarma%' OR EVENT_HANDLER LIKE '%voiso%'
ORDER BY ID");

echo "=== Zadarma app ===\n";
rows($m, "SELECT ID, CLIENT_ID, CODE, ACTIVE, STATUS, LEFT(APP_NAME,80) N, DATE_FINISH
FROM b_rest_app WHERE ID=77 OR CODE LIKE '%Zadarma%' OR CODE LIKE '%zadarma%'");

echo "=== Zadarma app options/settings ===\n";
rows($m, "SELECT * FROM b_rest_app WHERE ID=77\\G"); // may fail — fallback below
$q = $m->query("SHOW COLUMNS FROM b_rest_app");
$cols = [];
while ($c = $q->fetch_assoc()) {
    $cols[] = $c['Field'];
}
echo "b_rest_app cols: " . implode(',', $cols) . "\n";

echo "=== rest app lang/settings for 77 ===\n";
foreach (['b_rest_app_log', 'b_rest_placement', 'b_rest_event', 'b_rest_stat_app'] as $t) {
    $chk = $m->query("SHOW TABLES LIKE '$t'");
    if ($chk && $chk->num_rows) {
        echo "-- $t --\n";
    }
}
rows($m, "SELECT ID, APP_ID, PLACEMENT, LEFT(PLACEMENT_HANDLER,120) H FROM b_rest_placement WHERE APP_ID=77 LIMIT 40");

echo "=== voximplant lines ===\n";
$tables = [];
$q = $m->query("SHOW TABLES LIKE '%vox%'");
while ($r = $q->fetch_row()) {
    $tables[] = $r[0];
    echo "table $r[0]\n";
}
foreach ($tables as $t) {
    if (preg_match('/line|sip|user|config|phone/i', $t)) {
        echo "-- sample $t --\n";
        rows($m, "SELECT * FROM `$t` LIMIT 15");
    }
}

echo "=== telephony options ===\n";
rows($m, "SELECT MODULE_ID, NAME, LEFT(VALUE,200) V FROM b_option
WHERE MODULE_ID IN ('voximplant','telephony','call','im')
AND (NAME LIKE '%LINE%' OR NAME LIKE '%DEFAULT%' OR NAME LIKE '%PORTAL%' OR NAME LIKE '%MODE%' OR NAME LIKE '%SIP%' OR NAME LIKE '%EXTERNAL%')
LIMIT 80");

echo "=== recent call stats (if any) ===\n";
$q = $m->query("SHOW TABLES LIKE '%call%'");
while ($r = $q->fetch_row()) {
    echo "call-table: $r[0]\n";
}
$rowsCheck = $m->query("SHOW TABLES LIKE 'b_voximplant_statistic'");
if ($rowsCheck && $rowsCheck->num_rows) {
    rows($m, "SELECT ID, CALL_START_DATE, CALL_DURATION, PORTAL_NUMBER, PHONE_NUMBER, CALL_FAILED_CODE, CALL_FAILED_REASON, CALL_STATUS, CALL_TYPE
FROM b_voximplant_statistic ORDER BY ID DESC LIMIT 15");
}

echo "=== im call / external recent ===\n";
foreach (['b_call', 'b_im_call', 'b_voximplant_call'] as $t) {
    $chk = $m->query("SHOW TABLES LIKE '$t'");
    if ($chk && $chk->num_rows) {
        echo "-- $t cols --\n";
        rows($m, "SHOW COLUMNS FROM `$t`");
        rows($m, "SELECT * FROM `$t` ORDER BY 1 DESC LIMIT 8");
    }
}

echo "DONE\n";
