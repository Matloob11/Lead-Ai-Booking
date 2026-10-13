<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

function inflate(string $raw): string
{
    $try = @gzuncompress($raw);
    if ($try !== false) {
        return $try;
    }
    $try = @gzdecode($raw);
    if ($try !== false) {
        return $try;
    }
    return $raw;
}

$q = $m->query("SELECT ID, NAME, TEMPLATE FROM b_bp_workflow_template WHERE DOCUMENT_TYPE='LEAD' AND ACTIVE='Y'");
while ($r = $q->fetch_assoc()) {
    $text = inflate($r['TEMPLATE']);
    if (!preg_match('/n8n|outreach|whatsapp|webhook|hstgr|alots/i', $text)) {
        continue;
    }
    echo "ID={$r['ID']} {$r['NAME']}\n";
    preg_match_all('#https?://[^\\s"\']+#i', $text, $urls);
    foreach (array_unique($urls[0] ?? []) as $u) {
        echo "  " . substr($u, 0, 220) . "\n";
    }
    if (empty($urls[0])) {
        if (preg_match_all('/.{0,40}(n8n|outreach|webhook).{0,80}/i', $text, $bits)) {
            foreach (array_slice($bits[0], 0, 6) as $b) {
                echo "  ~ " . preg_replace('/\s+/', ' ', $b) . "\n";
            }
        }
    }
}
