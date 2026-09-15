<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
    fwrite(STDERR, $m->connect_error . PHP_EOL);
    exit(1);
}
$sql = "SELECT ID, EVENT_NAME, LEFT(EVENT_HANDLER,150) AS H, APP_ID
        FROM b_rest_event
        WHERE EVENT_NAME IN ('ONEXTERNALCALLSTART','ONEXTERNALCALLBACKSTART')
        ORDER BY ID";
$q = $m->query($sql);
while ($r = $q->fetch_assoc()) {
    echo $r['ID'] . "\t" . $r['EVENT_NAME'] . "\t" . $r['APP_ID'] . "\t" . $r['H'] . PHP_EOL;
}
