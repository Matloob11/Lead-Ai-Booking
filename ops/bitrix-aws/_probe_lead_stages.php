<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');
echo "=== lead statuses ===\n";
$q = $m->query("SELECT ID, STATUS_ID, NAME, SORT, `SYSTEM` AS SYS FROM b_crm_status WHERE ENTITY_ID='STATUS' ORDER BY SORT");
while ($r = $q->fetch_assoc()) {
    echo implode(' | ', $r), "\n";
}
