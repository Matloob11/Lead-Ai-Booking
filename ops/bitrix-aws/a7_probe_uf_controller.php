<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$file = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/lib/controller/userfieldconfig.php';
$txt = file_get_contents($file);
echo "bytes=", strlen($txt), "\n";
preg_match_all('/function\s+(\w+)\s*\(/', $txt, $m);
echo "methods:\n", implode("\n", $m[1] ?? []), "\n";
// show configureActions if any
if (preg_match('/function configureActions.*?^\}/ms', $txt, $cfg)) {
	echo "--- configureActions ---\n", $cfg[0], "\n";
}
// show add/create related chunks
foreach (['addAction', 'createAction', 'updateAction', 'saveAction'] as $fn) {
	if (preg_match('/function ' . $fn . '.*?^(?:\t| {4})\}/ms', $txt, $chunk)) {
		echo "--- $fn ---\n", substr($chunk[0], 0, 800), "\n";
	}
}
// also list ajax action names from attributes
preg_match_all('/ActionName|Action\(|#\[.*?\]/', $txt, $a);
echo "attrs sample: ", implode(' | ', array_slice($a[0] ?? [], 0, 30)), "\n";
