<?php
/**
 * Disable Voiso Bitrix click-to-call handlers so Zadarma receives ONEXTERNALCALLSTART.
 * Safe: only removes Voiso (cc-ams04) external-call event rows.
 */
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
    fwrite(STDERR, $m->connect_error . PHP_EOL);
    exit(1);
}

echo "=== BEFORE ===\n";
$q = $m->query(
    "SELECT ID, EVENT_NAME, LEFT(EVENT_HANDLER,140) H, APP_ID
     FROM b_rest_event
     WHERE EVENT_NAME IN ('ONEXTERNALCALLSTART','ONEXTERNALCALLBACKSTART')
     ORDER BY ID"
);
while ($r = $q->fetch_assoc()) {
    echo $r['ID'] . "\t" . $r['EVENT_NAME'] . "\t" . $r['APP_ID'] . "\t" . $r['H'] . "\n";
}

// Backup Voiso rows then delete.
$m->query(
    "CREATE TABLE IF NOT EXISTS a7_rest_event_voiso_backup LIKE b_rest_event"
);
$m->query(
    "INSERT IGNORE INTO a7_rest_event_voiso_backup
     SELECT * FROM b_rest_event
     WHERE EVENT_HANDLER LIKE '%voiso%'
        OR EVENT_HANDLER LIKE '%cc-ams04%'"
);
$deleted = 0;
$res = $m->query(
    "SELECT ID FROM b_rest_event
     WHERE EVENT_HANDLER LIKE '%voiso%'
        OR EVENT_HANDLER LIKE '%cc-ams04%'"
);
$ids = [];
while ($r = $res->fetch_assoc()) {
    $ids[] = (int)$r['ID'];
}
if ($ids) {
    $in = implode(',', $ids);
    $m->query("DELETE FROM b_rest_event WHERE ID IN ($in)");
    $deleted = $m->affected_rows;
}

echo "=== DELETED voiso rows: $deleted (" . implode(',', $ids) . ") ===\n";

echo "=== AFTER ===\n";
$q = $m->query(
    "SELECT ID, EVENT_NAME, LEFT(EVENT_HANDLER,140) H, APP_ID
     FROM b_rest_event
     WHERE EVENT_NAME IN ('ONEXTERNALCALLSTART','ONEXTERNALCALLBACKSTART')
     ORDER BY ID"
);
while ($r = $q->fetch_assoc()) {
    echo $r['ID'] . "\t" . $r['EVENT_NAME'] . "\t" . $r['APP_ID'] . "\t" . $r['H'] . "\n";
}

$z = $m->query(
    "SELECT ID, CODE, ACTIVE, APP_NAME FROM b_rest_app WHERE ID=77 OR CODE LIKE '%Zadarma%'"
);
echo "=== ZADARMA APP ===\n";
while ($r = $z->fetch_assoc()) {
    echo $r['ID'] . "\t" . $r['CODE'] . "\t" . $r['ACTIVE'] . "\t" . $r['APP_NAME'] . "\n";
}

echo "OK\n";
