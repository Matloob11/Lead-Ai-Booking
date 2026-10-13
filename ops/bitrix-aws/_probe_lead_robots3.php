<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

echo "=== lead templates ===\n";
$q = $m->query("SELECT ID, DOCUMENT_TYPE, NAME, AUTO_EXECUTE, ACTIVE, LENGTH(TEMPLATE) L
FROM b_bp_workflow_template
WHERE DOCUMENT_TYPE LIKE '%LEAD%' OR ENTITY LIKE '%LEAD%'
ORDER BY ID DESC LIMIT 40");
while ($r = $q->fetch_assoc()) {
    echo implode(' | ', $r), "\n";
}

echo "=== url-ish snippets ===\n";
$q = $m->query("SELECT ID, NAME FROM b_bp_workflow_template
WHERE TEMPLATE LIKE '%http%' AND (DOCUMENT_TYPE LIKE '%LEAD%' OR NAME LIKE '%lead%' OR NAME LIKE '%WA%' OR NAME LIKE '%Whats%')
LIMIT 30");
if (!$q) echo $m->error, "\n";
while ($q && ($r = $q->fetch_assoc())) {
    echo $r['ID'], ' ', $r['NAME'], "\n";
}
