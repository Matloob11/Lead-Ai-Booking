<?php
/**
 * Empty Hostinger leads (a7-pf, no beds/community/budget) that also have
 * another lead on the same phone. Writes a restore file. Does not delete.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

function digits($v) {
    return preg_replace('/\D/', '', (string)$v);
}

$where = "l.ORIGINATOR_ID='a7-pf'
  AND (l.COMMENTS LIKE '%PF lead %' OR l.COMMENTS LIKE 'Agent:%')
  AND (u.UF_CRM_1731838126127 IS NULL OR u.UF_CRM_1731838126127='')
  AND (u.UF_CRM_1770537051525 IS NULL OR u.UF_CRM_1770537051525='')
  AND (u.UF_CRM_1763390140 IS NULL OR u.UF_CRM_1763390140='')
  AND (u.UF_CRM_1736306439793 IS NULL OR u.UF_CRM_1736306439793='' OR u.UF_CRM_1736306439793='0')";

$empty = [];
$q = $m->query("SELECT l.ID, l.TITLE, l.NAME, l.LAST_NAME, l.STATUS_ID, s.NAME STAGE,
  l.ASSIGNED_BY_ID, TRIM(CONCAT(ag.NAME,' ',ag.LAST_NAME)) AGENT,
  l.DATE_CREATE, l.ORIGIN_ID, l.COMMENTS, l.SOURCE_ID
  FROM b_crm_lead l
  LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
  LEFT JOIN b_crm_status s ON s.STATUS_ID=l.STATUS_ID AND s.ENTITY_ID='STATUS'
  LEFT JOIN b_user ag ON ag.ID=l.ASSIGNED_BY_ID
  WHERE $where");
if (!$q) {
    fwrite(STDERR, $m->error . "\n");
    exit(1);
}
while ($r = $q->fetch_assoc()) {
    $empty[(int)$r['ID']] = $r;
}
echo 'EMPTY ' . count($empty) . "\n";

$phones = [];
$ids = array_keys($empty);
foreach (array_chunk($ids, 400) as $chunk) {
    $in = implode(',', $chunk);
    $pq = $m->query("SELECT ELEMENT_ID, VALUE FROM b_crm_field_multi WHERE ENTITY_ID='LEAD' AND TYPE_ID='PHONE' AND ELEMENT_ID IN ($in)");
    while ($p = $pq->fetch_assoc()) {
        $d = digits($p['VALUE']);
        if (strlen($d) < 8) continue;
        $phones[(int)$p['ELEMENT_ID']][] = $d;
    }
}

$need = [];
foreach ($phones as $id => $list) {
    foreach ($list as $d) $need[$d] = true;
}
echo 'PHONES ' . count($need) . "\n";

$twins = [];
foreach (array_chunk(array_keys($need), 200) as $chunk) {
    $vals = [];
    foreach ($chunk as $d) {
        $vals[] = "'" . $m->real_escape_string($d) . "'";
        $vals[] = "'" . $m->real_escape_string('+' . $d) . "'";
    }
    $in = implode(',', $vals);
    $tq = $m->query("SELECT fm.ELEMENT_ID, fm.VALUE, l.ORIGINATOR_ID
      FROM b_crm_field_multi fm
      JOIN b_crm_lead l ON l.ID=fm.ELEMENT_ID
      WHERE fm.ENTITY_ID='LEAD' AND fm.TYPE_ID='PHONE' AND fm.VALUE IN ($in)");
    if (!$tq) {
        fwrite(STDERR, $m->error . "\n");
        exit(1);
    }
    while ($t = $tq->fetch_assoc()) {
        $d = digits($t['VALUE']);
        $lid = (int)$t['ELEMENT_ID'];
        if (isset($empty[$lid])) continue;
        $twins[$d][] = $lid;
    }
}

$drop = [];
$keep = 0;
foreach ($empty as $id => $row) {
    $hit = [];
    foreach ($phones[$id] ?? [] as $d) {
        foreach ($twins[$d] ?? [] as $other) $hit[$other] = true;
    }
    if ($hit) {
        $row['PHONES'] = $phones[$id] ?? [];
        $row['TWIN_IDS'] = array_keys($hit);
        $drop[] = $row;
    } else {
        $keep++;
    }
}

$path = '/tmp/a7pf-empty-dupes-20260930.json';
file_put_contents($path, json_encode($drop, JSON_UNESCAPED_UNICODE));
echo 'DROP ' . count($drop) . "\n";
echo 'KEEP ' . $keep . "\n";
echo 'BACKUP ' . $path . "\n";
if ($drop) {
    $s0 = $drop[0];
    echo 'SAMPLE ' . $s0['ID'] . ' twins ' . implode(',', array_slice($s0['TWIN_IDS'], 0, 3)) . "\n";
}
