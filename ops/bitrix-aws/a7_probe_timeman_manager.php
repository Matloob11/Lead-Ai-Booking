<?php
$files = [
	'/home/bitrix/www/bitrix/modules/timeman/classes/general/timeman.php',
	'/home/bitrix/www/bitrix/modules/timeman/classes/general/timeman_user.php',
];
foreach ($files as $f) {
	if (!is_file($f)) continue;
	$src = file_get_contents($f);
	$pos = stripos($src, 'function getUserManagers');
	if ($pos === false) $pos = stripos($src, 'function GetUserManagers');
	echo "FILE $f pos=$pos\n";
	if ($pos !== false) echo substr($src, $pos, 2200) . "\n----\n";
}
