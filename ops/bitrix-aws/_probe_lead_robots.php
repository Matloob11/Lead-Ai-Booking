<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
    fwrite(STDERR, $m->connect_error . PHP_EOL);
    exit(1);
}
$m->set_charset('utf8mb4');

function rows(mysqli $m, string $sql): void
{
    $q = $m->query($sql);
    if (!$q) {
        echo "SQL ERR: " . $m->error . "\n";
        return;
    }
    $n = 0;
    while ($r = $q->fetch_assoc()) {
        $n++;
        $parts = [];
        foreach ($r as $k => $v) {
            $text = is_null($v) ? 'NULL' : str_replace(["\n", "\r", "\t"], ' ', (string)$v);
            if (strlen($text) > 220) {
                $text = substr($text, 0, 220) . '…';
            }
            $parts[] = $k . '=' . $text;
        }
        echo implode(' | ', $parts) . "\n";
    }
    echo "rows=$n\n";
}

echo "=== rest events n8n/wa ===\n";
rows($m, "SELECT ID, EVENT_NAME, APP_ID, LEFT(EVENT_HANDLER,180) H FROM b_rest_event
WHERE EVENT_HANDLER LIKE '%n8n%' OR EVENT_HANDLER LIKE '%outreach%' OR EVENT_HANDLER LIKE '%whatsapp%'
   OR EVENT_NAME LIKE '%LEAD%'
LIMIT 40");

echo "=== bp templates mentioning n8n or outreach ===\n";
$q = $m->query("SHOW TABLES LIKE '%bp%'");
while ($q && ($r = $q->fetch_row())) {
    echo $r[0] . "\n";
}
