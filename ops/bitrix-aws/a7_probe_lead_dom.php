<?php
/**
 * Dump entity-editor field markup for a portal lead (server-rendered snippet if any).
 * Also list English empty placeholder from lang.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

// Find the locale string for empty UF
$paths = [
	'/bitrix/modules/ui/lang/en/ui.entity-editor.php',
	'/bitrix/modules/crm/lang/en/lib/Service/EditorAdapter.php',
	'/bitrix/js/ui/entity-editor/lang/en/config.php',
];
foreach ($paths as $p) {
	$full = $_SERVER['DOCUMENT_ROOT'] . $p;
	if (!is_file($full)) {
		continue;
	}
	$txt = file_get_contents($full);
	if (preg_match_all('/field is empty|EMPTY|not filled|is empty/i', $txt, $m)) {
		echo $p, " hits=", count($m[0]), "\n";
	}
}
passthru('rg -l -i "field is empty" ' . escapeshellarg($_SERVER['DOCUMENT_ROOT'] . '/bitrix/js/ui') . ' 2>/dev/null | head -10');
passthru('rg -n -i "field is empty" ' . escapeshellarg($_SERVER['DOCUMENT_ROOT'] . '/bitrix') . ' --glob "*.php" --glob "*.js" 2>/dev/null | head -20');

echo "lead 79318 source:\n";
$row = \Bitrix\Main\Application::getConnection()->query(
	"SELECT ID, TITLE, SOURCE_ID FROM b_crm_lead WHERE ID=79318"
)->fetch();
print_r($row);
