<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');
$q = $m->query("SELECT COUNT(*) N FROM b_crm_lead WHERE DATE_CREATE >= '2026-09-26 00:00:00' AND DATE_CREATE < '2026-09-27 00:00:00'");
echo 'UTC_DAY ', $q->fetch_assoc()['N'], "\n";
$q = $m->query("SELECT COUNT(*) N FROM b_crm_lead WHERE DATE_CREATE >= '2026-09-25 19:00:00' AND DATE_CREATE < '2026-09-26 19:00:00'");
echo 'PKT_DAY ', $q->fetch_assoc()['N'], "\n";
