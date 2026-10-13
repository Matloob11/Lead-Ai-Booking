<?php
$file = '/home/bitrix/www/bitrix/components/bitrix/crm.lead.details/class.php';
$txt = file_get_contents($file);
echo "bytes ", strlen($txt), "\n";
foreach (['function prepareFieldInfos', 'function prepareConfiguration', 'availableFields'] as $n) {
	$p = strpos($txt, $n);
	echo "$n pos=$p\n";
}
$p = strpos($txt, 'function prepareFieldInfos');
echo substr($txt, $p, 2500), "\n";
