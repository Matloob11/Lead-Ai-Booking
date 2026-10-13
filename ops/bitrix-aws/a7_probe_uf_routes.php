<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$dirs = [
	$_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/ui/lib',
	$_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/crm/lib',
	$_SERVER['DOCUMENT_ROOT'] . '/bitrix/components/bitrix',
];
$needles = ['userfieldconfig', 'UserFieldConfig', 'createField', 'UserFieldFactory', 'addField'];
foreach ($needles as $needle) {
	echo "=== $needle ===\n";
	$found = 0;
	foreach ($dirs as $dir) {
		if (!is_dir($dir)) {
			continue;
		}
		$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS));
		foreach ($it as $file) {
			if (!$file->isFile()) {
				continue;
			}
			$name = $file->getFilename();
			if (!preg_match('/\.(php|js)$/i', $name)) {
				continue;
			}
			if (stripos($name, $needle) === false && stripos($file->getPathname(), $needle) === false) {
				// peek content only for likely names
				if (!preg_match('/userfield|fieldfactory|fieldconfig/i', $name)) {
					continue;
				}
			}
			$path = $file->getPathname();
			if (stripos($path, $needle) !== false || stripos($name, $needle) !== false) {
				echo substr($path, strlen($_SERVER['DOCUMENT_ROOT'])), "\n";
				$found++;
				if ($found >= 12) {
					break 2;
				}
			}
		}
	}
	if ($found === 0) {
		echo "(none by path)\n";
	}
}

// Controllers under main that mention UserType Add
echo "=== controllers mentioning UserType ===\n";
$ctrl = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/lib/controller';
if (is_dir($ctrl)) {
	$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($ctrl, FilesystemIterator::SKIP_DOTS));
	foreach ($it as $file) {
		if (!$file->isFile() || !str_ends_with(strtolower($file->getFilename()), '.php')) {
			continue;
		}
		$txt = @file_get_contents($file->getPathname(), false, null, 0, 8000);
		if ($txt && (stripos($txt, 'UserType') !== false || stripos($txt, 'userfield') !== false)) {
			echo substr($file->getPathname(), strlen($_SERVER['DOCUMENT_ROOT'])), "\n";
		}
	}
}
