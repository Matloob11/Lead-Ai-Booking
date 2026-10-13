<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$file = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/js/crm/common.js';
$txt = file_get_contents($file);
$needles = [
	'BX.Crm.PartialEditorDialog = function',
	'PartialEditorDialog.prototype',
	'checkErrorTitle',
	'More on required',
	'checkErrorHelp',
];
foreach ($needles as $n) {
	$p = 0;
	$i = 0;
	echo "=== $n ===\n";
	while (($p = strpos($txt, $n, $p)) !== false && $i < 3) {
		echo "pos $p\n";
		echo substr($txt, max(0, $p - 120), 900), "\n----\n";
		$p += strlen($n);
		$i++;
	}
}
