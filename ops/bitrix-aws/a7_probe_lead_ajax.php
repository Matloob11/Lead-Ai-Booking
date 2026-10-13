<?php
$paths = [
	'/home/bitrix/www/bitrix/components/bitrix/crm.lead.details/ajax.php',
	'/home/bitrix/www/bitrix/modules/crm/install/components/bitrix/crm.lead.details/ajax.php',
];
foreach ($paths as $p) {
	echo "exists ", $p, " ", (is_file($p) ? 'yes '.filesize($p) : 'no'), "\n";
}
$file = is_file($paths[0]) ? $paths[0] : $paths[1];
$txt = file_get_contents($file);
$p = strpos($txt, 'PREPARE_EDITOR_HTML');
echo "pos $p\n";
echo substr($txt, max(0, $p - 200), 3500), "\n";
