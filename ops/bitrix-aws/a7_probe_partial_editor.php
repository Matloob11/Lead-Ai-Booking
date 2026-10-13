<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$file = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/js/crm/common.js';
$txt = file_get_contents($file);
echo "bytes ", strlen($txt), "\n";
$needles = ['PartialEditorDialog', 'checkErrorTitle', 'fieldNames', 'open'];
foreach (['BX.Crm.PartialEditorDialog', 'PartialEditorDialog.create', 'checkErrorTitle'] as $n) {
	$p = strpos($txt, $n);
	echo $n, " pos=", $p, "\n";
}
$p = strpos($txt, 'BX.Crm.PartialEditorDialog = function');
if ($p === false) {
	$p = strpos($txt, 'PartialEditorDialog');
}
if ($p !== false) {
	echo "\n----- snippet -----\n";
	echo substr($txt, $p, 4500), "\n";
}
