<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
    fwrite(STDERR, $m->connect_error . "\n");
    exit(1);
}

$want = [
    // leaders
    'hassan', 'javeria', 'javeria', 'hussnain', 'rana muhammad',
    // hassan team
    'khazeema', 'aila', 'sapna', 'uzma', 'haram', 'ariba', 'eman', 'ruqia',
    // hussnain team
    'mehnaz', 'nimra', 'tehreem', 'mehreen', 'isha', 'warda', 'momina', 'irum',
    // jaweria team
    'farhat', 'fozia', 'menahil', 'asma aslam', 'asma', 'shareen',
];

$q = $m->query("SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, SECOND_NAME, ACTIVE, PERSONAL_MOBILE, WORK_POSITION
FROM b_user
WHERE ACTIVE='Y'
ORDER BY ID");

$all = [];
while ($r = $q->fetch_assoc()) {
    $full = trim(($r['NAME'] ?? '') . ' ' . ($r['LAST_NAME'] ?? '') . ' ' . ($r['SECOND_NAME'] ?? ''));
    $full = preg_replace('/\s+/', ' ', $full);
    $hay = strtolower($full . ' ' . ($r['EMAIL'] ?? '') . ' ' . ($r['LOGIN'] ?? ''));
    $all[] = [
        'id' => (int)$r['ID'],
        'name' => $full,
        'email' => (string)$r['EMAIL'],
        'login' => (string)$r['LOGIN'],
        'position' => (string)$r['WORK_POSITION'],
        'hay' => $hay,
    ];
}

function findUsers(array $all, string $needle): array
{
    $n = strtolower(trim($needle));
    $hits = [];
    foreach ($all as $u) {
        if ($n !== '' && (strpos($u['hay'], $n) !== false || strpos(strtolower($u['name']), $n) !== false)) {
            $hits[] = $u;
        }
    }
    return $hits;
}

$teams = [
    'Hassan' => [
        'leader_email' => 'hassan.a7group@gmail.com',
        'leader_id' => 2560,
        'agents' => ['Khazeema','Aila','Sapna','Uzma','Haram','Ariba','Eman','Ruqia'],
    ],
    'Hussnain' => [
        'leader_email' => 'Ranahussnain.a7group@gmail.com',
        'leader_id' => 2551,
        'agents' => ['Mehnaz','Nimra','Tehreem','Mehreen','Isha','Warda','Momina','Irum'],
    ],
    'Jaweria' => [
        'leader_email' => 'javeriabibi.a7group@gmail.com',
        'leader_id' => 2297,
        'agents' => ['Farhat','Fozia','Menahil','Asma Aslam','Shareen'],
    ],
];

foreach ($teams as $lead => $meta) {
    echo "===== TEAM $lead =====\n";
    $leader = null;
    foreach ($all as $u) {
        if ($u['id'] === (int)$meta['leader_id'] || strcasecmp($u['email'], $meta['leader_email']) === 0) {
            $leader = $u;
            break;
        }
    }
    if ($leader) {
        echo "LEADER\t{$leader['id']}\t{$leader['name']}\t{$leader['email']}\t{$leader['position']}\n";
    } else {
        echo "LEADER\tNOT FOUND id={$meta['leader_id']} email={$meta['leader_email']}\n";
    }
    foreach ($meta['agents'] as $agentName) {
        $hits = findUsers($all, $agentName);
        // prefer a7group emails / sales-looking
        usort($hits, static function ($a, $b) {
            $sa = (stripos($a['email'], 'a7group') !== false ? 0 : 1);
            $sb = (stripos($b['email'], 'a7group') !== false ? 0 : 1);
            if ($sa !== $sb) {
                return $sa - $sb;
            }
            return $a['id'] - $b['id'];
        });
        if (!$hits) {
            echo "AGENT\t$agentName\tNO MATCH\n";
            continue;
        }
        // show top 3 if ambiguous
        $show = array_slice($hits, 0, 3);
        foreach ($show as $i => $h) {
            $tag = $i === 0 ? 'PICK?' : 'alt';
            echo "AGENT\t$agentName\t$tag\t{$h['id']}\t{$h['name']}\t{$h['email']}\t{$h['position']}\n";
        }
    }
    echo "\n";
}

echo "=== exact leader rows ===\n";
foreach ([2560, 2551, 2297] as $id) {
    foreach ($all as $u) {
        if ($u['id'] === $id) {
            echo json_encode($u, JSON_UNESCAPED_SLASHES) . "\n";
        }
    }
}
