<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');
$q = $m->query("SELECT l.ID, l.TITLE, l.NAME, l.LAST_NAME, l.STATUS_ID, s.NAME STAGE,
  l.ASSIGNED_BY_ID, TRIM(CONCAT(ag.NAME,' ',ag.LAST_NAME)) AGENT,
  l.DATE_CREATE, l.ORIGIN_ID, l.COMMENTS, l.SOURCE_ID
  FROM b_crm_lead l
  LEFT JOIN b_crm_status s ON s.STATUS_ID=l.STATUS_ID AND s.ENTITY_ID='STATUS'
  LEFT JOIN b_user ag ON ag.ID=l.ASSIGNED_BY_ID
  WHERE l.ORIGINATOR_ID='a7-pf'
    AND (l.COMMENTS LIKE '%PF lead %' OR l.COMMENTS LIKE 'Agent:%')");
if (!$q) { fwrite(STDERR, $m->error."\n"); exit(1); }
$rows = [];
while ($r = $q->fetch_assoc()) $rows[(int)$r['ID']] = $r;
if ($rows) {
    foreach (array_chunk(array_keys($rows), 400) as $chunk) {
        $in = implode(',', $chunk);
        $pq = $m->query("SELECT ELEMENT_ID, VALUE FROM b_crm_field_multi WHERE ENTITY_ID='LEAD' AND TYPE_ID='PHONE' AND ELEMENT_ID IN ($in)");
        while ($p = $pq->fetch_assoc()) {
            $id = (int)$p['ELEMENT_ID'];
            $rows[$id]['PHONES'][] = preg_replace('/\D/', '', $p['VALUE']);
        }
    }
}
foreach ($rows as &$row) {
    $row['TWIN_IDS'] = [];
    if (!isset($row['PHONES'])) $row['PHONES'] = [];
}
unset($row);
$out = array_values($rows);
file_put_contents('/tmp/a7pf-remaining-20261001.json', json_encode($out, JSON_UNESCAPED_UNICODE));
echo 'EXPORT ' . count($out) . "\n";
