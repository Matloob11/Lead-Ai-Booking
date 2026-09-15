<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

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

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$items = $factory->getItems([
	'select' => ['ID', 'TITLE', 'ASSIGNED_BY_ID', 'PARENT_ID_1058'],
	'filter' => ['CATEGORY_ID' => 14],
	'limit' => 20000,
]);

function person(array $users, $uid): string
{
	$uid = (int)$uid;
	if ($uid <= 0) {
		return 'unassigned';
	}
	return $users[$uid] ?? ('user ' . $uid);
}

$byField = [];
$byFieldWho = [];
$fieldFilled = 0;
$fieldBlank = 0;
$titleOnly = [];
$titleOnlyWho = [];
$titleOnlyN = 0;

$needles = [];
foreach ($comms as $id => $title) {
	$t = trim($title);
	if (strlen($t) >= 4) {
		$needles[] = [$id, $t, strlen($t)];
	}
}
usort($needles, fn($a, $b) => $b[2] <=> $a[2]);

foreach ($items as $item) {
	$uid = (int)$item->getAssignedById();
	$who = person($users, $uid);
	$cid = (int)$item->get('PARENT_ID_1058');
	$title = (string)$item->getTitle();

	if ($cid > 0) {
		$fieldFilled++;
		$cname = $comms[$cid] ?? ('community #' . $cid);
		$byField[$cname] = ($byField[$cname] ?? 0) + 1;
		$byFieldWho[$cname][$who] = ($byFieldWho[$cname][$who] ?? 0) + 1;
		continue;
	}

	$fieldBlank++;
	$hit = null;
	$low = mb_strtolower($title);
	foreach ($needles as $n) {
		if (mb_strpos($low, mb_strtolower($n[1])) !== false) {
			$hit = $n[1];
			break;
		}
	}
	if ($hit) {
		$titleOnlyN++;
		$titleOnly[$hit] = ($titleOnly[$hit] ?? 0) + 1;
		$titleOnlyWho[$hit][$who] = ($titleOnlyWho[$hit][$who] ?? 0) + 1;
	}
}

echo "total=" . count($items) . "\n";
echo "community_field_filled=$fieldFilled\n";
echo "community_field_blank=$fieldBlank\n";
echo "title_inferred=$titleOnlyN\n";
echo "no_community_at_all=" . ($fieldBlank - $titleOnlyN) . "\n";

echo "=== FIELD communities ===\n";
arsort($byField);
foreach ($byField as $name => $c) {
	echo "COMM\t$c\t$name\n";
	$who = $byFieldWho[$name];
	arsort($who);
	foreach ($who as $person => $n) {
		echo "WHO\t$n\t$name\t$person\n";
	}
}

echo "=== TITLE-ONLY communities ===\n";
arsort($titleOnly);
foreach ($titleOnly as $name => $c) {
	echo "TCOMM\t$c\t$name\n";
	$who = $titleOnlyWho[$name];
	arsort($who);
	foreach ($who as $person => $n) {
		echo "TWHO\t$n\t$name\t$person\n";
	}
}
echo "DONE\n";
