<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

echo "=== templates ===\n";
$sql = "SELECT ID, MODULE_ID, ENTITY, DOCUMENT_TYPE, NAME, AUTO_EXECUTE, ACTIVE
FROM b_bp_workflow_template
WHERE TEMPLATE LIKE '%n8n%' OR TEMPLATE LIKE '%outreach%' OR TEMPLATE LIKE '%a7-bitrix%'
   OR NAME LIKE '%WhatsApp%' OR NAME LIKE '%n8n%' OR NAME LIKE '%Sara%' OR NAME LIKE '%outreach%'
LIMIT 50";
$q = $m->query($sql);
if (!$q) {
    echo $m->error, "\n";
    exit(1);
}
while ($r = $q->fetch_assoc()) {
    echo implode(' | ', $r), "\n";
}

echo "=== n8n events ===\n";
$q = $m->query("SELECT ID, EVENT_NAME, LEFT(EVENT_HANDLER,180) H FROM b_rest_event
WHERE EVENT_HANDLER LIKE '%n8n%' OR EVENT_HANDLER LIKE '%hstgr%' OR EVENT_HANDLER LIKE '%a7-bitrix%' OR EVENT_HANDLER LIKE '%outreach%'
LIMIT 30");
while ($r = $q->fetch_assoc()) {
    echo implode(' | ', $r), "\n";
}
