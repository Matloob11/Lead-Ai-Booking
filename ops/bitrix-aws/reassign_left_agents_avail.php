<?php
/**
 * Availability only (cat 14, not Old Leads): leftover community cards
 * of agents who left → current community owners (xlsx + dubai jpeg).
 * No-community and unmapped communities stay. APPLY=1 to write.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$apply = getenv('APPLY') === '1';
$oldStage = 'DT1042_14:UC_YCY8JG';
$leavers = [7, 2378, 2296, 2293, 2294, 15, 2292, 2300, 2218];

$owners = [
	'international_city' => [2302, 2298, 2299, 2390, 2392],
	'villanova' => [2344, 2429],
	'lagoons' => [2434, 2291],
	'serena' => [2368, 2367],
	'valley' => [2350],
	'ranches' => [2379, 2380, 2376],
	'mudon' => [8, 27, 2219, 30, 2361, 24],
];
$rr = [];

function bucket(?string $name): ?string
{
	if ($name === null || $name === '' || $name === '(no community)') {
		return null;
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
	if ($n === 'the valley' || strpos($n, 'the valley') !== false) {
		return 'valley';
	}
	if (strpos($n, 'arabian ranches') !== false || $n === 'caya' || $n === 'raya' || $n === 'joy' || $n === 'anya' || $n === 'sun' || strpos($n, 'bliss') !== false) {
		return 'ranches';
	}
	if (strpos($n, 'mudon') !== false) {
		return 'mudon';
	}
	return null;
}

function nextOwner(array $owners, array &$rr, string $bucket): int
{
	$list = $owners[$bucket];
	$i = $rr[$bucket] ?? 0;
	$uid = $list[$i % count($list)];
	$rr[$bucket] = $i + 1;
	return $uid;
}

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$users = [];
$q = $m->query("SELECT ID, NAME, LAST_NAME, ACTIVE FROM b_user WHERE ID IN (" . implode(',', array_merge($leavers, ...array_values($owners))) . ")");
while ($r = $q->fetch_assoc()) {
	$users[(int)$r['ID']] = trim($r['NAME'] . ' ' . $r['LAST_NAME']) . ($r['ACTIVE'] === 'Y' ? '' : ' (inactive)');
}
echo "=== leavers ===\n";
foreach ($leavers as $id) {
	echo $id . "\t" . ($users[$id] ?? '?') . "\n";
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
$inList = implode(',', $leavers);
$items = $factory->getItems([
	'select' => ['ID', 'TITLE', 'ASSIGNED_BY_ID', 'PARENT_ID_1058', 'STAGE_ID', 'CATEGORY_ID'],
	'filter' => [
		'CATEGORY_ID' => 14,
		'!STAGE_ID' => $oldStage,
		'ASSIGNED_BY_ID' => $leavers,
	],
	'limit' => 5000,
]);

$plan = [];
$skipNo = 0;
$skipUnmapped = [];
$byFrom = [];

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
	$fromName = $users[$from] ?? ('user ' . $from);
	if ($b === null) {
		if ($cname === '' || $cname === '(no community)') {
			$skipNo++;
		} else {
			$skipUnmapped[$cname] = ($skipUnmapped[$cname] ?? 0) + 1;
			echo "UNMAPPED\t" . $item->getId() . "\t$fromName\t$cname\n";
		}
		continue;
	}
	$to = nextOwner($owners, $rr, $b);
	$plan[] = [
		'id' => (int)$item->getId(),
		'from' => $from,
		'to' => $to,
		'comm' => $cname,
		'bucket' => $b,
	];
	$key = $fromName . ' -> ' . ($users[$to] ?? $to) . ' | ' . $cname;
	$byFrom[$key] = ($byFrom[$key] ?? 0) + 1;
}

echo "apply=" . ($apply ? 'yes' : 'no') . "\n";
echo "scanned=" . count($items) . "\n";
echo "will_reassign=" . count($plan) . "\n";
echo "skip_no_community=$skipNo\n";
echo "=== plan ===\n";
ksort($byFrom);
foreach ($byFrom as $k => $c) {
	echo "$c\t$k\n";
}
echo "=== unmapped community totals ===\n";
arsort($skipUnmapped);
foreach ($skipUnmapped as $n => $c) {
	echo "$c\t$n\n";
}

if (!$apply) {
	echo "DRY_RUN\n";
	exit(0);
}

$ok = 0;
$fail = 0;
foreach ($plan as $row) {
	$item = $factory->getItem($row['id']);
	if (!$item || (int)$item->getCategoryId() !== 14 || (string)$item->getStageId() === $oldStage) {
		$fail++;
		echo "FAIL skip " . $row['id'] . "\n";
		continue;
	}
	$item->setAssignedById($row['to']);
	$op = $factory->getUpdateOperation($item);
	$op->disableCheckAccess();
	if (method_exists($op, 'disableAutomation')) {
		$op->disableAutomation();
	}
	if (method_exists($op, 'disableBizProc')) {
		$op->disableBizProc();
	}
	$res = $op->launch();
	if ($res->isSuccess()) {
		$ok++;
	} else {
		$fail++;
		echo "FAIL " . $row['id'] . " " . implode('; ', $res->getErrorMessages()) . "\n";
	}
}
echo "reassign_ok=$ok reassign_fail=$fail\n";

$left = $factory->getItemsCount([
	'CATEGORY_ID' => 14,
	'!STAGE_ID' => $oldStage,
	'ASSIGNED_BY_ID' => $leavers,
]);
echo "leavers_still_hold_except_old=$left\n";
echo "DONE\n";
