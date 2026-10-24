<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') {
	http_response_code(404);
	exit;
}
foreach ([
	'/home/bitrix/www/bitrix/php_interface/init.php',
	'/home/bitrix/www/local/php_interface/init.php',
] as $path) {
	echo "==== $path exists=" . (is_file($path) ? 'yes' : 'no') . " ====\n";
	if (!is_file($path)) {
		continue;
	}
	$lines = file($path);
	foreach ($lines as $i => $line) {
		if (preg_match('/require|include|a7_/i', $line)) {
			echo ($i + 1) . ':' . rtrim($line) . "\n";
		}
	}
}
