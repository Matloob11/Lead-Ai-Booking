<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('humanresources');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== HR related tables ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_hr%'");
while ($r = $q->fetch_row()) {
	echo $r[0] . "\n";
}

echo "=== member / role tables sample ===\n";
foreach (['b_hr_structure_node_member', 'b_hr_structure_node_role', 'b_hr_structure_node_path'] as $t) {
	$chk = $m->query("SHOW TABLES LIKE '$t'");
	if (!$chk || !$chk->num_rows) {
		echo "missing $t\n";
		continue;
	}
	$cols = [];
	$cq = $m->query("SHOW COLUMNS FROM `$t`");
	while ($c = $cq->fetch_assoc()) {
		$cols[] = $c['Field'];
	}
	echo "$t cols=" . implode(',', $cols) . "\n";
	$sq = $m->query("SELECT * FROM `$t` WHERE NODE_ID IN (59,60,61) LIMIT 20");
	if (!$sq) {
		// try alternate column
		$sq = $m->query("SELECT * FROM `$t` LIMIT 5");
	}
	while ($r = $sq->fetch_assoc()) {
		echo json_encode($r) . "\n";
	}
}

echo "=== entity link iblock <-> hr ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_hr%relation%'");
while ($r = $q->fetch_row()) echo $r[0] . "\n";
$q = $m->query("SHOW COLUMNS FROM b_hr_structure_node");
while ($c = $q->fetch_assoc()) { /* already know */ }

// XML_ID might map to iblock section
$q = $m->query("SELECT ID,NAME,XML_ID,PARENT_ID FROM b_hr_structure_node WHERE ID IN (50,59,60,61,31)");
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== classes for member add ===\n";
foreach ([
	'Bitrix\\HumanResources\\Service\\Container',
	'Bitrix\\HumanResources\\Repository\\NodeMemberRepository',
	'Bitrix\\HumanResources\\Item\\NodeMember',
	'Bitrix\\HumanResources\\Enum\\NodeType',
	'Bitrix\\Intranet\\HumanResources\\Synchronizer',
	'Bitrix\\HumanResources\\Compat\\Structure',
] as $c) {
	echo (class_exists($c) ? 'YES ' : 'no  ') . $c . "\n";
}

if (class_exists(\Bitrix\HumanResources\Service\Container::class)) {
	$ref = new ReflectionClass(\Bitrix\HumanResources\Service\Container::class);
	foreach ($ref->getMethods(ReflectionMethod::IS_PUBLIC | ReflectionMethod::IS_STATIC) as $meth) {
		if (stripos($meth->name, 'Member') !== false
			|| stripos($meth->name, 'Node') !== false
			|| stripos($meth->name, 'Sync') !== false
			|| stripos($meth->name, 'Department') !== false
		) {
			echo 'Container::' . $meth->name . "\n";
		}
	}
}

echo "=== CRM Controller Manager methods ===\n";
if (class_exists(\Bitrix\Crm\Security\Controller\Manager::class)) {
	$ref = new ReflectionClass(\Bitrix\Crm\Security\Controller\Manager::class);
	foreach ($ref->getMethods() as $meth) {
		echo 'Manager::' . $meth->name . "\n";
	}
}

echo "=== access attrs for lead assignee 2434 ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_crm_access_attr_lead'");
if ($q->num_rows) {
	$cq = $m->query('SHOW COLUMNS FROM b_crm_access_attr_lead');
	while ($c = $cq->fetch_assoc()) echo $c['Field'] . ' ';
	echo "\n";
	$leadId = 0;
	$lq = $m->query('SELECT ID FROM b_crm_lead WHERE ASSIGNED_BY_ID=2434 ORDER BY ID DESC LIMIT 1');
	if ($r = $lq->fetch_assoc()) {
		$leadId = (int)$r['ID'];
		echo "lead=$leadId\n";
		$aq = $m->query("SELECT * FROM b_crm_access_attr_lead WHERE ENTITY_ID=$leadId LIMIT 30");
		while ($a = $aq->fetch_assoc()) echo json_encode($a) . "\n";
	}
}

echo "=== Hassan codes now ===\n";
$access = new CAccess();
$access->UpdateCodes(['USER_ID' => 2560]);
$res = CAccess::GetUserCodes(2560);
while ($c = $res->Fetch()) {
	$ac = $c['ACCESS_CODE'];
	if (preg_match('/^(D|DR|SND|SNDR|IU)/', $ac)) {
		echo $c['PROVIDER_ID'] . ':' . $ac . "\n";
	}
}
