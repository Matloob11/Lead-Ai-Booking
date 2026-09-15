<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$needles = [
	// xlsx team leads + members
	'javaria', 'javeria', 'hassan', 'hasnain',
	'fozia', 'asma', 'farhat', 'sheereen', 'shareen', 'shereen', 'minahil',
	'aila', 'nabiha', 'eman', 'khazeema', 'areeba',
	'sapna', 'uzma',
	'nimra', 'mahnaz', 'mehnaz', 'tehreem', 'mehreen',
	'esha', 'warda', 'inum', 'irum',
	// jpeg dubai agents
	'manna', 'qasim', 'amina', 'kausar', 'hajara', 'akmal', 'rashmi',
	'neha', 'saneha', 'sneha', 'isra', 'irsa', 'qadir', 'shahid',
	'ramzan', 'sajid',
];

echo "=== candidate users ===\n";
$q = $m->query("SELECT ID, NAME, LAST_NAME, LOGIN, EMAIL, ACTIVE FROM b_user ORDER BY ID");
$allUsers = [];
while ($r = $q->fetch_assoc()) {
	$full = trim($r['NAME'] . ' ' . $r['LAST_NAME']);
	$blob = strtolower($full . ' ' . $r['LOGIN'] . ' ' . $r['EMAIL']);
	$allUsers[(int)$r['ID']] = [
		'name' => $full !== '' ? $full : $r['LOGIN'],
		'active' => $r['ACTIVE'],
		'login' => $r['LOGIN'],
		'blob' => $blob,
	];
	$hit = false;
	foreach ($needles as $n) {
		if (strpos($blob, $n) !== false) {
			$hit = true;
			break;
		}
	}
	if ($hit) {
		echo $r['ID'] . "\t" . $r['ACTIVE'] . "\t" . $full . "\t" . $r['LOGIN'] . "\n";
	}
}

$inTeam = [
	2297, // Javeria bibi
	2302, // Fozia
	2298, // Asma
	2299, // Farhat Shahid
	2390, // shareen
	2392, // minahil
	2344, // Aila
	2429, // NABIHA
	2379, // eman
	2380, // Khazeema
	2376, // Areeba
	2434, // SAPNA
	2291, // uzma
	2369, // nimra
	2371, // tehreem
	2535, // Mehreen
	2368, // Esha
	2367, // Warda
	2350, // Irum
	8,    // Qasim
	10,   // Akmal
	2360, // Rashmi
	2251, // Neha
	2361, // Sneha
	30,   // Irsa
	2258, // Qadir
	24,   // Ramzan
	23,   // Sajid
];

$comms = [];
$q = $m->query("SELECT ID, TITLE FROM b_crm_dynamic_items_1058");
while ($r = $q->fetch_assoc()) {
	$comms[(int)$r['ID']] = trim((string)$r['TITLE']);
}
$needlesComm = [];
foreach ($comms as $id => $title) {
	if (strlen($title) >= 4 && !in_array(strtolower($title), ['dubai', 'test'], true)) {
		$needlesComm[] = [$id, $title, strlen($title)];
	}
}
usort($needlesComm, fn($a, $b) => $b[2] <=> $a[2]);

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$items = $factory->getItems([
	'select' => ['ID', 'TITLE', 'ASSIGNED_BY_ID', 'PARENT_ID_1058'],
	'filter' => ['CATEGORY_ID' => 14],
	'limit' => 20000,
]);

$inSet = array_flip($inTeam);
$byWho = [];
$byWhoComm = [];
$teamCount = 0;
$outCount = 0;

foreach ($items as $item) {
	$uid = (int)$item->getAssignedById();
	$cid = (int)$item->get('PARENT_ID_1058');
	$title = (string)$item->getTitle();
	$cname = '';
	if ($cid > 0) {
		$cname = $comms[$cid] ?? ('community #' . $cid);
	} else {
		$low = mb_strtolower($title);
		foreach ($needlesComm as $n) {
			if (mb_strpos($low, mb_strtolower($n[1])) !== false) {
				$cname = $n[1];
				break;
			}
		}
	}
	if ($cname === '') {
		$cname = '(no community)';
	}

	if (isset($inSet[$uid])) {
		$teamCount++;
		continue;
	}

	$outCount++;
	$info = $allUsers[$uid] ?? ['name' => 'user ' . $uid, 'active' => '?'];
	$label = $info['name'];
	if (($info['active'] ?? '') === 'N') {
		$label .= ' (inactive)';
	}
	$byWho[$uid] = ($byWho[$uid] ?? ['label' => $label, 'c' => 0]);
	$byWho[$uid]['c']++;
	$byWhoComm[$uid][$cname] = ($byWhoComm[$uid][$cname] ?? 0) + 1;
}

echo "=== totals ===\n";
echo "availability_total=" . count($items) . "\n";
echo "on_listed_agents=$teamCount\n";
echo "outside_listed_agents=$outCount\n";
echo "outside_people=" . count($byWho) . "\n";

uasort($byWho, fn($a, $b) => $b['c'] <=> $a['c']);
echo "=== outside assignees ===\n";
foreach ($byWho as $uid => $row) {
	echo "WHO\t" . $row['c'] . "\t$uid\t" . $row['label'] . "\n";
	$commsHere = $byWhoComm[$uid];
	arsort($commsHere);
	foreach ($commsHere as $cname => $n) {
		echo "COMM\t$n\t" . $row['label'] . "\t$cname\n";
	}
}
echo "DONE\n";
