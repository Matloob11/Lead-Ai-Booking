<?php
/**
 * Availability actionable stages only: community-wise assign to ACTIVE
 * agents from Team_Community_Allocation + dubai agents.jpeg.
 * Unmapped / no-community → all active members, round-robin.
 * APPLY=0 plan; APPLY=1 SQL assign (stage unchanged).
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$apply = getenv('APPLY') === '1';
$stages = [
	'DT1042_14:NEW',
	'DT1042_14:UC_73SP7H',
	'DT1042_14:PREPARATION',
	'DT1042_14:UC_G0PCBL',
	'DT1042_14:UC_39DSJP',
	'DT1042_14:UC_76AZKL',
	'DT1042_14:UC_PKIJWV',
];

$candidates = [
	2302, 2298, 2299, 2390, 2392, 2258, 23, 31,
	2344, 2429, 10, 2360,
	2434, 2291, 2251,
	2368, 2367, 8, 27, 2219, 24,
	2350, 2361, 30,
	2379, 2380, 2376,
	2369, 2381, 2371, 2535,
];

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$users = [];
$in = implode(',', $candidates);
$q = $m->query("SELECT ID, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID IN ($in)");
while ($r = $q->fetch_assoc()) {
	$users[(int)$r['ID']] = [
		'name' => trim($r['NAME'] . ' ' . $r['LAST_NAME']),
		'active' => $r['ACTIVE'] === 'Y',
	];
}

$active = [];
echo "=== candidate status ===\n";
foreach ($candidates as $id) {
	$u = $users[$id] ?? null;
	$ok = $u && $u['active'];
	echo ($ok ? 'OK' : 'SKIP') . "\t$id\t" . ($u['name'] ?? 'MISSING') . "\t" . ($u['active'] ?? false ? 'Y' : 'N') . "\n";
	if ($ok) {
		$active[] = $id;
	}
}

$haj = $m->query("SELECT ID, NAME, LAST_NAME, ACTIVE FROM b_user WHERE (NAME LIKE '%Hajara%' OR LAST_NAME LIKE '%Hajara%' OR CONCAT(NAME,' ',LAST_NAME) LIKE '%Hajara%') AND ACTIVE='Y'");
echo "=== hajara ===\n";
while ($r = $haj->fetch_assoc()) {
	echo json_encode($r) . "\n";
	$hid = (int)$r['ID'];
	if (!in_array($hid, $active, true)) {
		$active[] = $hid;
		$users[$hid] = ['name' => trim($r['NAME'] . ' ' . $r['LAST_NAME']), 'active' => true];
	}
}

$pools = [
	'international_city' => array_values(array_intersect($active, [2302, 2298, 2299, 2390, 2392, 2258, 23, 31])),
	'villanova' => array_values(array_intersect($active, [2344, 2429, 10, 2360])),
	'lagoons' => array_values(array_intersect($active, [2434, 2291, 2251])),
	'serena' => array_values(array_intersect($active, [2368, 2367, 8, 27, 2219, 24, 2251])),
	'valley' => array_values(array_intersect($active, [2350, 2361])),
	'ranches' => array_values(array_intersect($active, [2379, 2380, 2376])),
	'mudon' => array_values(array_intersect($active, [8, 27, 2219, 30, 2361, 24])),
	'hills' => array_values(array_intersect($active, [2368, 2367])),
	'haven' => array_values(array_intersect($active, [2369, 2381])),
	'acres' => array_values(array_intersect($active, [2371, 2535])),
];
$allPool = $active;
$rr = [];

function bucket(?string $name): string
{
	if ($name === null || $name === '' || $name === '(no community)') {
		return 'other';
	}
	$n = mb_strtolower(trim($name));
	if (strpos($n, 'international city') !== false) {
		return 'international_city';
	}
	if (strpos($n, 'villanova') !== false) {
		return 'villanova';
	}
	if (strpos($n, 'lagoon') !== false) {
		return 'lagoons';
	}
	if (strpos($n, 'serena') !== false) {
		return 'serena';
	}
	if (strpos($n, 'the valley') !== false) {
		return 'valley';
	}
	if (strpos($n, 'arabian ranches') !== false || $n === 'caya' || $n === 'raya' || $n === 'joy' || $n === 'anya' || $n === 'sun' || strpos($n, 'bliss') !== false) {
		return 'ranches';
	}
	if (strpos($n, 'mudon') !== false) {
		return 'mudon';
	}
	if (strpos($n, 'hills') !== false) {
		return 'hills';
	}
	if (strpos($n, 'haven') !== false) {
		return 'haven';
	}
	if (strpos($n, 'acres') !== false) {
		return 'acres';
	}
	return 'other';
}

function nextOwner(array $pool, array &$rr, string $key): int
{
	if (!$pool) {
		throw new RuntimeException("empty pool $key");
	}
	$i = $rr[$key] ?? 0;
	$uid = $pool[$i % count($pool)];
	$rr[$key] = $i + 1;
	return $uid;
}

$comms = [];
$q = $m->query("SELECT ID, TITLE FROM b_crm_dynamic_items_1058");
while ($r = $q->fetch_assoc()) {
	$comms[(int)$r['ID']] = trim((string)$r['TITLE']);
}
$needles = [];
foreach ($comms as $id => $title) {
	if (strlen($title) >= 4 && !in_array(strtolower($title), ['dubai', 'test'], true)) {
		$needles[] = [$title, strlen($title)];
	}
}
usort($needles, fn($a, $b) => $b[1] <=> $a[1]);

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$items = $factory->getItems([
	'select' => ['ID', 'TITLE', 'ASSIGNED_BY_ID', 'PARENT_ID_1058', 'STAGE_ID', 'CATEGORY_ID'],
	'filter' => [
		'CATEGORY_ID' => 14,
		'STAGE_ID' => $stages,
	],
	'limit' => 20000,
]);

$plan = [];
$byTo = [];
$byBucket = [];
$unchanged = 0;

foreach ($items as $item) {
	if ((int)$item->getCategoryId() !== 14) {
		continue;
	}
	$from = (int)$item->getAssignedById();
	$cid = (int)$item->get('PARENT_ID_1058');
	$cname = '';
	if ($cid > 0) {
		$cname = $comms[$cid] ?? ('community #' . $cid);
	} else {
		$low = mb_strtolower((string)$item->getTitle());
		foreach ($needles as $n) {
			if (mb_strpos($low, mb_strtolower($n[0])) !== false) {
				$cname = $n[0];
				break;
			}
		}
	}
	$b = bucket($cname === '' ? null : $cname);
	$pool = ($b !== 'other' && !empty($pools[$b])) ? $pools[$b] : $allPool;
	$to = nextOwner($pool, $rr, $b);
	if ($to === $from) {
		$unchanged++;
		continue;
	}
	$plan[] = ['id' => (int)$item->getId(), 'to' => $to, 'from' => $from, 'b' => $b];
	$toName = $users[$to]['name'] ?? ('user ' . $to);
	$byTo[$toName] = ($byTo[$toName] ?? 0) + 1;
	$byBucket[$b] = ($byBucket[$b] ?? 0) + 1;
}

echo "scanned=" . count($items) . "\n";
echo "will_change=" . count($plan) . "\n";
echo "already_correct=$unchanged\n";
echo "=== by bucket (changes) ===\n";
arsort($byBucket);
foreach ($byBucket as $b => $c) {
	echo "$c\t$b\n";
}
echo "=== by receiver (changes) ===\n";
arsort($byTo);
foreach ($byTo as $n => $c) {
	echo "$c\t$n\n";
}

if (!$apply) {
	echo "DRY_RUN\n";
	exit(0);
}

$ok = 0;
foreach ($plan as $row) {
	$id = (int)$row['id'];
	$to = (int)$row['to'];
	$m->query(
		"UPDATE b_crm_dynamic_items_1042
		 SET ASSIGNED_BY_ID='$to', UPDATED_BY=1, UPDATED_TIME=NOW()
		 WHERE ID=$id AND CATEGORY_ID=14
		   AND STAGE_ID IN ('" . implode("','", $stages) . "')"
	);
	if ($m->affected_rows >= 0) {
		$ok++;
	}
}
echo "sql_updates=$ok\n";

$bad = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN b_user u ON u.ID=CAST(i.ASSIGNED_BY_ID AS UNSIGNED)
	 WHERE i.CATEGORY_ID=14
	   AND i.STAGE_ID IN ('" . implode("','", $stages) . "')
	   AND (u.ID IS NULL OR u.ACTIVE<>'Y')"
)->fetch_assoc()['c'];
$admin = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND ASSIGNED_BY_ID='1'
	   AND STAGE_ID IN ('" . implode("','", $stages) . "')"
)->fetch_assoc()['c'];
echo "still_on_inactive=$bad\n";
echo "still_on_admin=$admin\n";
echo "DONE\n";
