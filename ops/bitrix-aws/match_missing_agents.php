<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$need = ['haram', 'ariba', 'areeba', 'menahil', 'minahil', 'isha', 'ayesha', 'eman', 'mehreen', 'mahreen'];
$q = $m->query("SELECT ID,NAME,LAST_NAME,EMAIL,LOGIN,ACTIVE FROM b_user WHERE ACTIVE='Y' ORDER BY ID");
while ($r = $q->fetch_assoc()) {
    $hay = strtolower(trim($r['NAME'] . ' ' . $r['LAST_NAME'] . ' ' . $r['EMAIL'] . ' ' . $r['LOGIN']));
    foreach ($need as $n) {
        if (strpos($hay, $n) !== false) {
            echo $r['ID'] . "\t" . trim($r['NAME'] . ' ' . $r['LAST_NAME']) . "\t" . $r['EMAIL'] . "\tmatch=$n\n";
            break;
        }
    }
}

echo "=== a7group users sample (sales-looking) ===\n";
$q = $m->query("SELECT ID,NAME,LAST_NAME,EMAIL FROM b_user WHERE ACTIVE='Y' AND (EMAIL LIKE '%a7group%' OR EMAIL LIKE '%a7gre%' OR EMAIL LIKE '%a7properties%') ORDER BY ID");
while ($r = $q->fetch_assoc()) {
    echo $r['ID'] . "\t" . trim($r['NAME'] . ' ' . $r['LAST_NAME']) . "\t" . $r['EMAIL'] . "\n";
}
