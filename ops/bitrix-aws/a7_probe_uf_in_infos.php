<?php
$file = '/home/bitrix/www/bitrix/components/bitrix/crm.lead.details/class.php';
$txt = file_get_contents($file);
$p = strpos($txt, 'function prepareFieldInfos');
$chunk = substr($txt, $p, 18000);
foreach (['userField', 'UserField', 'GetEntityFields', 'crm.userfield', 'appendUser'] as $n) {
	$i = stripos($chunk, $n);
	echo "$n in prepareFieldInfos chunk: ", ($i === false ? 'no' : $i), "\n";
}
// parent call?
if (preg_match('/function prepareFieldInfos\(\)[\s\S]{0,200}parent::/', $txt, $m)) {
	echo "calls parent\n";
}
$p2 = strpos($txt, 'prepareUserFields');
echo "prepareUserFields pos $p2\n";
$p3 = strpos($txt, 'CCrmUserType');
echo "CCrmUserType pos $p3\n";
if ($p3) {
	echo substr($txt, $p3 - 200, 800), "\n";
}
