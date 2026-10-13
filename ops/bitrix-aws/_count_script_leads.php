<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');
$q = $m->query("SELECT
  COUNT(*) total,
  SUM(CASE WHEN COMMENTS LIKE '%PF lead %' OR COMMENTS LIKE 'Agent:%' THEN 1 ELSE 0 END) made_by_script,
  SUM(CASE WHEN COMMENTS LIKE 'Listing ID:%' THEN 1 ELSE 0 END) listing_id_comment
FROM b_crm_lead WHERE ORIGINATOR_ID='a7-pf'");
$r = $q->fetch_assoc();
echo implode(' | ', $r), "\n";
