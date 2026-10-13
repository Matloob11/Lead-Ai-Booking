<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$file = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/crm/classes/general/crm_view_helper.php';
$txt = file_get_contents($file);
$pos = stripos($txt, 'STAGE_MANAGER_CHECK_ERROR');
echo "file bytes ", strlen($txt), " pos ", $pos, "\n";
if ($pos !== false) {
	echo substr($txt, max(0, $pos - 500), 2500), "\n";
}
echo "\n=== js refs ===\n";
passthru('grep -R -l "STAGE_MANAGER_CHECK_ERROR" ' . escapeshellarg($_SERVER['DOCUMENT_ROOT'] . '/bitrix/js/crm') . ' ' . escapeshellarg($_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/crm') . ' 2>/dev/null | head -20');
