<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
    fwrite(STDERR, $m->connect_error . "\n");
    exit(1);
}

echo "=== ONEXTERNAL handlers + apps ===\n";
$q = $m->query("SELECT e.ID,e.EVENT_NAME,e.APP_ID,e.EVENT_HANDLER,a.CODE,a.ACTIVE,a.STATUS,a.APP_NAME
FROM b_rest_event e LEFT JOIN b_rest_app a ON a.ID=e.APP_ID
WHERE e.EVENT_NAME IN ('ONEXTERNALCALLSTART','ONEXTERNALCALLBACKSTART') ORDER BY e.ID");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
}

echo "=== apps 22,59,77 detail ===\n";
$q = $m->query("SELECT * FROM b_rest_app WHERE ID IN (22,59,77)");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
}

echo "=== voximplant/telephony options ===\n";
$q = $m->query("SELECT MODULE_ID,NAME,LEFT(VALUE,350) V FROM b_option
WHERE MODULE_ID IN ('voximplant','telephony','crm','im')
AND (NAME LIKE '%line%' OR NAME LIKE '%default%' OR NAME LIKE '%portal%' OR NAME LIKE '%mode%'
  OR NAME LIKE '%external%' OR NAME LIKE '%sip%' OR NAME LIKE '%rest%' OR NAME LIKE '%number%' OR NAME LIKE '%phone%')
ORDER BY MODULE_ID,NAME");
while ($r = $q->fetch_assoc()) {
    echo $r['MODULE_ID'] . "\t" . $r['NAME'] . "\t" . str_replace(["\n","\t"], [' ',' '], $r['V']) . "\n";
}

echo "=== voximplant tables ===\n";
$tq = $m->query("SHOW TABLES LIKE 'b_voximplant%'");
while ($t = $tq->fetch_row()) {
    $name = $t[0];
    $cnt = (int)$m->query("SELECT COUNT(*) c FROM `$name`")->fetch_assoc()['c'];
    echo "TABLE $name count=$cnt\n";
    if ($cnt === 0) {
        continue;
    }
    $limit = $cnt < 500 ? 10 : 5;
    $order = $cnt >= 500 ? ' ORDER BY 1 DESC' : '';
    $q = $m->query("SELECT * FROM `$name`$order LIMIT $limit");
    while ($r = $q->fetch_assoc()) {
        echo '  ' . json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
    }
}

echo "=== recent statistic ===\n";
$c = $m->query("SHOW TABLES LIKE 'b_voximplant_statistic'");
if ($c && $c->num_rows) {
    $q = $m->query("SELECT ID,CALL_START_DATE,CALL_DURATION,PORTAL_NUMBER,PHONE_NUMBER,CALL_FAILED_CODE,CALL_FAILED_REASON,CALL_STATUS,CALL_TYPE,EXTERNAL_CALL_ID
FROM b_voximplant_statistic ORDER BY ID DESC LIMIT 25");
    if (!$q) {
        // columns may differ
        $q = $m->query('SELECT * FROM b_voximplant_statistic ORDER BY ID DESC LIMIT 15');
    }
    while ($r = $q->fetch_assoc()) {
        echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
    }
} else {
    echo "no statistic table\n";
}

echo "=== external lines ===\n";
$c = $m->query("SHOW TABLES LIKE 'b_voximplant_external_line'");
if ($c && $c->num_rows) {
    $q = $m->query('SELECT * FROM b_voximplant_external_line');
    while ($r = $q->fetch_assoc()) {
        echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
    }
}

echo "=== rest placements telephony ===\n";
$q = $m->query("SELECT ID,APP_ID,PLACEMENT,LEFT(PLACEMENT_HANDLER,160) H FROM b_rest_placement
WHERE PLACEMENT LIKE '%CALL%' OR PLACEMENT LIKE '%PHONE%' OR PLACEMENT LIKE '%TELE%' OR PLACEMENT_HANDLER LIKE '%zadarma%' LIMIT 40");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_SLASHES) . "\n";
}

echo "DONE\n";
