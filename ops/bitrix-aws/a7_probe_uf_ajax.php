<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$root = $_SERVER['DOCUMENT_ROOT'];
$needles = [
	'userfieldconfig',
	'UserFieldConfig',
	'createField',
	'addUserField',
	'FIELD_CREATE',
	'ui.userfieldfactory',
];
foreach ($needles as $n) {
	echo "=== $n ===\n";
	passthru(
		'rg -l -i --max-count=1 ' . escapeshellarg($n) . ' '
		. escapeshellarg($root . '/bitrix/modules/ui') . ' '
		. escapeshellarg($root . '/bitrix/modules/crm') . ' '
		. escapeshellarg($root . '/bitrix/components/bitrix')
		. ' 2>/dev/null | head -15'
	);
}
echo "=== OnBeforeUserTypeAdd handler sample ===\n";
$file = $root . '/bitrix/modules/main/classes/general/usertype.php';
$txt = file_get_contents($file);
if (preg_match('/OnBeforeUserTypeAdd.{0,400}/s', $txt, $m)) {
	echo $m[0], "\n";
}
