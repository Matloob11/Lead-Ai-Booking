<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

echo "=== total a7-pf ===\n";
$q = $m->query("SELECT COUNT(*) N, MIN(DATE_CREATE) first_at, MAX(DATE_CREATE) last_at FROM b_crm_lead WHERE ORIGINATOR_ID='a7-pf'");
echo implode(' | ', $q->fetch_assoc()), "\n";

echo "=== by stage ===\n";
$q = $m->query("SELECT s.NAME stage, COUNT(*) N
FROM b_crm_lead l
LEFT JOIN b_crm_status s ON s.STATUS_ID=l.STATUS_ID AND s.ENTITY_ID='STATUS'
WHERE l.ORIGINATOR_ID='a7-pf'
GROUP BY s.NAME ORDER BY N DESC");
while ($r = $q->fetch_assoc()) echo $r['N'], ' | ', $r['stage'], "\n";

echo "=== by assignee ===\n";
$q = $m->query("SELECT CONCAT(u.NAME, ' ', u.LAST_NAME) agent, COUNT(*) N
FROM b_crm_lead l
LEFT JOIN b_user u ON u.ID=l.ASSIGNED_BY_ID
WHERE l.ORIGINATOR_ID='a7-pf'
GROUP BY l.ASSIGNED_BY_ID ORDER BY N DESC");
while ($r = $q->fetch_assoc()) echo $r['N'], ' | ', trim($r['agent']), "\n";

echo "=== stage x assignee ===\n";
$q = $m->query("SELECT s.NAME stage, CONCAT(u.NAME, ' ', u.LAST_NAME) agent, COUNT(*) N
FROM b_crm_lead l
LEFT JOIN b_crm_status s ON s.STATUS_ID=l.STATUS_ID AND s.ENTITY_ID='STATUS'
LEFT JOIN b_user u ON u.ID=l.ASSIGNED_BY_ID
WHERE l.ORIGINATOR_ID='a7-pf'
GROUP BY s.NAME, l.ASSIGNED_BY_ID
ORDER BY s.NAME, N DESC");
while ($r = $q->fetch_assoc()) echo $r['N'], ' | ', $r['stage'], ' | ', trim($r['agent']), "\n";
