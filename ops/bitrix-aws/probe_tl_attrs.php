<?php
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('intranet');

$uids = [2560, 2551, 2297];
foreach ($uids as $uid) {
	echo "==== USER $uid ====\n";
	$u = CUser::GetByID($uid)->Fetch();
	echo 'UF_DEPARTMENT=' . json_encode($u['UF_DEPARTMENT']) . "\n";

	global $DB;
	$r2 = $DB->Query(
		"SELECT r.ID, r.NAME, ru.RELATION
		 FROM b_crm_role_relation ru
		 JOIN b_crm_role r ON r.ID=ru.ROLE_ID
		 WHERE ru.RELATION='U{$uid}' OR ru.RELATION='G12'"
	);
	while ($row = $r2->Fetch()) {
		echo 'role ' . json_encode($row) . "\n";
	}

	$depts = is_array($u['UF_DEPARTMENT']) ? $u['UF_DEPARTMENT'] : [];
	foreach ($depts as $d) {
		$sec = CIBlockSection::GetList(
			[],
			['ID' => $d, 'IBLOCK_ID' => 3],
			false,
			['ID', 'NAME', 'UF_HEAD', 'IBLOCK_SECTION_ID']
		)->Fetch();
		echo 'dept ' . json_encode($sec) . "\n";
	}

	$ap = new \Bitrix\Crm\Security\AttributesProvider($uid);
	$attrs = $ap->getUserAttributes();
	echo 'attrs keys=' . implode(',', array_keys($attrs)) . "\n";
	foreach (['INTRANET', 'USER', 'HR_DEPARTMENTS', 'HR_SUBDEPARTMENTS', 'OPENED'] as $k) {
		if (isset($attrs[$k])) {
			echo "$k=" . json_encode($attrs[$k]) . "\n";
		}
	}

	$perms = new CCrmPerms($uid);
	foreach (['LEAD', 'DYNAMIC_1042', 'DYNAMIC_1042_C13', 'DYNAMIC_1042_C14'] as $e) {
		echo "$e READ=" . $perms->GetPermType($e, 'READ')
			. ' WRITE=' . $perms->GetPermType($e, 'WRITE') . "\n";
	}
}
