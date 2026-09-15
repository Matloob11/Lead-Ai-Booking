<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$toStage = 'DT1042_14:UC_YCY8JG';
$users = [];
$q = $m->query("SELECT ID, NAME, LAST_NAME, LOGIN, ACTIVE FROM b_user");
while ($r = $q->fetch_assoc()) {
	$name = trim($r['NAME'] . ' ' . $r['LAST_NAME']);
	if ($name === '') {
		$name = $r['LOGIN'] ?: ('user ' . $r['ID']);
	}
	if ($r['ACTIVE'] !== 'Y') {
		$name .= ' (inactive)';
	}
	$users[(int)$r['ID']] = $name;
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
	'select' => ['ID', 'TITLE', 'ASSIGNED_BY_ID', 'PARENT_ID_1058', 'CREATED_TIME', 'CATEGORY_ID'],
	'filter' => [
		'CATEGORY_ID' => 14,
		'STAGE_ID' => $toStage,
	],
	'limit' => 20000,
]);

$byWho = [];
$byWhoComm = [];
$byComm = [];
$noComm = 0;

foreach ($items as $item) {
	if ((int)$item->getCategoryId() !== 14) {
		continue;
	}
	$uid = (int)$item->getAssignedById();
	$who = $users[$uid] ?? ('user ' . $uid);
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
	if ($cname === '') {
		$cname = '(no community)';
		$noComm++;
	}
	$byWho[$who] = ($byWho[$who] ?? 0) + 1;
	$byWhoComm[$who][$cname] = ($byWhoComm[$who][$cname] ?? 0) + 1;
	$byComm[$cname] = ($byComm[$cname] ?? 0) + 1;
}

echo "old_stage_total=" . count($items) . "\n";
echo "no_community=$noComm\n";
arsort($byWho);
echo "=== by assignee ===\n";
foreach ($byWho as $who => $c) {
	echo "WHO\t$c\t$who\n";
	$commsHere = $byWhoComm[$who];
	arsort($commsHere);
	foreach ($commsHere as $cname => $n) {
		echo "COMM\t$n\t$who\t$cname\n";
	}
}
arsort($byComm);
echo "=== by community ===\n";
foreach ($byComm as $cname => $c) {
	echo "CTOT\t$c\t$cname\n";
}
echo "DONE\n";
