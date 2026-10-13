<?php
/**
 * Find how UserField create is hooked / what events exist.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$roots = [
	$_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/lib/userfield',
	$_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/classes/general',
	$_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/crm/lib/Service',
	$_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/ui/lib',
];

foreach (['OnBeforeUserTypeAdd', 'OnBeforeUserFieldAdd', 'userfieldconfig', 'UserField', 'addField'] as $needle) {
	echo "=== search $needle ===\n";
	$cmd = 'rg -l --max-count=1 ' . escapeshellarg($needle) . ' '
		. escapeshellarg($_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main') . ' '
		. escapeshellarg($_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/crm') . ' 2>/dev/null | head -20';
	passthru($cmd);
}

echo "=== CUserTypeEntity events ===\n";
$file = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/classes/general/usertype.php';
if (is_file($file)) {
	$txt = file_get_contents($file);
	preg_match_all('/OnBefore\w+|OnAfter\w+|ExecuteModuleEventEx\([^)]+\)/', $txt, $m);
	echo implode("\n", array_unique($m[0] ?? [])), "\n";
}
