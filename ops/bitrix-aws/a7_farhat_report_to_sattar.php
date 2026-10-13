<?php
/**
 * Farhat Shahid (2299) work reports "To" Abdul Sattar (32), not Javeria (2297).
 *
 * Durable: her subsection sits under company root (not Jaweria Team),
 * UF_DEPARTMENT is only that section, and Jaweria HR membership stays off
 * so Timeman getUserManagers first entry is Sattar.
 *
 * Run: sudo -u bitrix php thisfile.php
 */
declare(strict_types=1);

$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

const FARHAT = 2299;
const SATTAR = 32;
const JAVERIA = 2297;
const COMPANY_ROOT = 1;
const JAWERIA_TEAM = 71;
const IBLOCK = 3;
const SECTION_NAME = 'Farhat Shahid (work reports to Sattar)';

function a7_user(int $id): array
{
	$rs = CUser::GetByID($id);
	$row = $rs ? $rs->Fetch() : false;
	if (!$row) {
		fwrite(STDERR, "user $id missing\n");
		exit(1);
	}
	return $row;
}

$farhat = a7_user(FARHAT);
$sattar = a7_user(SATTAR);
if (stripos((string)$farhat['EMAIL'], 'farhat') === false && stripos((string)$farhat['NAME'], 'Farhat') === false) {
	fwrite(STDERR, "Refusing: 2299 is {$farhat['NAME']} {$farhat['LAST_NAME']} {$farhat['EMAIL']}\n");
	exit(1);
}
if (stripos((string)$sattar['EMAIL'], 'sattar') === false && stripos((string)$sattar['NAME'], 'Sattar') === false
	&& stripos((string)$sattar['LAST_NAME'], 'Sattar') === false) {
	fwrite(STDERR, "Refusing: 32 is {$sattar['NAME']} {$sattar['LAST_NAME']} {$sattar['EMAIL']}\n");
	exit(1);
}

echo 'farhat=' . $farhat['ID'] . ' ' . $farhat['NAME'] . ' ' . $farhat['LAST_NAME'] . "\n";
echo 'sattar=' . $sattar['ID'] . ' ' . $sattar['NAME'] . ' ' . $sattar['LAST_NAME'] . "\n";

if (!CModule::IncludeModule('iblock')) {
	fwrite(STDERR, "iblock missing\n");
	exit(1);
}

$existing = CIBlockSection::GetList(
	[],
	['IBLOCK_ID' => IBLOCK, 'NAME' => SECTION_NAME, 'CHECK_PERMISSIONS' => 'N'],
	false,
	['ID', 'NAME', 'IBLOCK_SECTION_ID', 'UF_HEAD']
)->Fetch();

$bs = new CIBlockSection();
$sectionId = (int)($existing['ID'] ?? 0);
$fields = [
	'IBLOCK_ID' => IBLOCK,
	'IBLOCK_SECTION_ID' => COMPANY_ROOT,
	'NAME' => SECTION_NAME,
	'ACTIVE' => 'Y',
	'UF_HEAD' => SATTAR,
];

if ($sectionId > 0) {
	$ok = $bs->Update($sectionId, $fields);
	echo ($ok ? 'ok' : 'FAIL') . " section $sectionId reparented under " . COMPANY_ROOT
		. ' head=' . SATTAR . ' ' . $bs->LAST_ERROR . "\n";
	if (!$ok) {
		exit(1);
	}
} else {
	$sectionId = (int)$bs->Add($fields);
	if ($sectionId <= 0) {
		fwrite(STDERR, 'section add failed: ' . $bs->LAST_ERROR . "\n");
		exit(1);
	}
	echo "section created id=$sectionId\n";
}

$user = new CUser();
$ok = $user->Update(FARHAT, ['UF_DEPARTMENT' => [$sectionId]]);
echo ($ok ? 'ok' : 'FAIL') . " UF_DEPARTMENT=[$sectionId] " . $user->LAST_ERROR . "\n";
if (!$ok) {
	exit(1);
}

$access = new CAccess();
$access->UpdateCodes(['USER_ID' => FARHAT]);
echo "codes rebuilt\n";

$c = \Bitrix\Main\Application::getConnection();

// Ensure HR node parent matches company root after iblock reparent (sync can lag).
$node = $c->query(
	"SELECT ID, NAME, PARENT_ID FROM b_hr_structure_node WHERE NAME='" . $c->getSqlHelper()->forSql(SECTION_NAME) . "' AND TYPE='DEPARTMENT' LIMIT 1"
)->fetch();
if (!$node) {
	fwrite(STDERR, "HR node for section not synced yet\n");
	exit(1);
}
$nodeId = (int)$node['ID'];
echo "hr_node=$nodeId parent=" . (int)$node['PARENT_ID'] . "\n";
if ((int)$node['PARENT_ID'] !== COMPANY_ROOT) {
	$c->queryExecute(
		"UPDATE b_hr_structure_node SET PARENT_ID=" . COMPANY_ROOT . " WHERE ID=" . $nodeId
	);
	echo "hr_node parent forced to " . COMPANY_ROOT . "\n";
}

$m = $c->query(
	"SELECT ID, ACTIVE FROM b_hr_structure_node_member WHERE ENTITY_TYPE='USER' AND ENTITY_ID=" . FARHAT
	. " AND NODE_ID=" . $nodeId . " LIMIT 1"
)->fetch();
if ($m) {
	$memberId = (int)$m['ID'];
	if (($m['ACTIVE'] ?? '') !== 'Y') {
		$c->queryExecute("UPDATE b_hr_structure_node_member SET ACTIVE='Y' WHERE ID=" . $memberId);
	}
	echo "hr member exists id=$memberId\n";
} else {
	$c->queryExecute(
		"INSERT INTO b_hr_structure_node_member (ENTITY_TYPE, ENTITY_ID, ACTIVE, NODE_ID, ADDED_BY) VALUES ('USER',"
		. FARHAT . ",'Y'," . $nodeId . ",1)"
	);
	$memberId = (int)$c->getInsertedId();
	echo "hr member inserted id=$memberId\n";
}
$role = $c->query(
	"SELECT ID FROM b_hr_structure_node_member_role WHERE MEMBER_ID=" . $memberId . " AND ROLE_ID=2 LIMIT 1"
)->fetch();
if (!$role) {
	$c->queryExecute(
		"INSERT INTO b_hr_structure_node_member_role (MEMBER_ID, ROLE_ID, CREATED_BY) VALUES (" . $memberId . ",2,1)"
	);
	echo "hr employee role added\n";
}

// Drop Jaweria Team HR membership so Timeman cannot pick Javeria first.
$jaweriaNode = $c->query(
	"SELECT ID FROM b_hr_structure_node WHERE NAME='Jaweria Team (TL)' AND TYPE='DEPARTMENT' LIMIT 1"
)->fetch();
if ($jaweriaNode) {
	$jNode = (int)$jaweriaNode['ID'];
	$c->queryExecute(
		"UPDATE b_hr_structure_node_member SET ACTIVE='N' WHERE ENTITY_TYPE='USER' AND ENTITY_ID=" . FARHAT
		. " AND NODE_ID=" . $jNode
	);
	echo "hr Jaweria node $jNode membership deactivated for Farhat\n";
}

if (function_exists('BXClearCache')) {
	BXClearCache(true);
}
\Bitrix\Main\Application::getInstance()->getManagedCache()->cleanAll();

if (!CModule::IncludeModule('timeman')) {
	fwrite(STDERR, "timeman missing\n");
	exit(1);
}
$tm = array_values((array)CTimeMan::GetUserManagers(FARHAT));
echo 'timeman_managers=' . json_encode($tm) . "\n";
$first = $tm ? (int)$tm[0] : 0;
echo 'work_report_to=' . $first . "\n";
if ($first !== SATTAR) {
	fwrite(STDERR, "To is still not Sattar\n");
	exit(1);
}

$again = CUser::GetByID(FARHAT)->Fetch();
echo 'saved_dept=' . json_encode($again['UF_DEPARTMENT'] ?? null) . "\n";
echo "DONE\n";
