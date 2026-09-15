<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== role 6 Employee LEAD/DYNAMIC ===\n";
$q = $m->query(
	"SELECT ENTITY,FIELD,PERM_TYPE,ATTR,SETTINGS FROM b_crm_role_perms
	 WHERE ROLE_ID=6
	   AND ENTITY IN ('LEAD','DYNAMIC_1042','DYNAMIC_1042_C13','DYNAMIC_1042_C14')
	   AND (FIELD='-' OR FIELD='' OR FIELD IS NULL)
	 ORDER BY ENTITY,PERM_TYPE"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== role 54 dash ===\n";
$q = $m->query(
	"SELECT ENTITY,FIELD,PERM_TYPE,ATTR,SETTINGS FROM b_crm_role_perms
	 WHERE ROLE_ID=54
	   AND ENTITY IN ('LEAD','DYNAMIC_1042','DYNAMIC_1042_C13','DYNAMIC_1042_C14')
	   AND (FIELD='-' OR FIELD='' OR FIELD IS NULL)
	 ORDER BY ENTITY,PERM_TYPE"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== Jaweria relations ===\n";
$q = $m->query(
	"SELECT * FROM b_crm_role_relation
	 WHERE RELATION LIKE '%2297%' OR RELATION LIKE 'D71%' OR RELATION LIKE 'DR71%'"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== sections ===\n";
$q = $m->query(
	"SELECT ID,NAME,IBLOCK_SECTION_ID,DEPTH_LEVEL FROM b_iblock_section
	 WHERE IBLOCK_ID=3 AND ID IN (69,70,71,60,41,65,31,59)"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== uts section heads ===\n";
$q = $m->query("SELECT * FROM b_uts_iblock_3_section WHERE VALUE_ID IN (69,70,71,60)");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

echo "=== access codes for Hassan 2560 (sample) ===\n";
$res = CAccess::GetUserCodes(2560);
$i = 0;
while ($c = $res->Fetch()) {
	if (str_contains((string)$c['ACCESS_CODE'], 'D69')
		|| str_contains((string)$c['ACCESS_CODE'], 'SND')
		|| str_contains((string)$c['ACCESS_CODE'], 'DR')
		|| $c['PROVIDER_ID'] === 'intranet'
		|| $c['PROVIDER_ID'] === 'department'
		|| $c['PROVIDER_ID'] === 'structure'
	) {
		echo json_encode($c) . "\n";
		if (++$i > 40) {
			break;
		}
	}
}

echo "=== how hr dept ids computed (attrs provider internals via reflection) ===\n";
$ap = new \Bitrix\Crm\Security\AttributesProvider(2560);
$ref = new ReflectionClass($ap);
// dump raw attributes again
echo json_encode($ap->getUserAttributes()) . "\n";
