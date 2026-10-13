<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$root = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/crm';
$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS));
$hits = 0;
foreach ($it as $file) {
	if (!$file->isFile() || !str_ends_with(strtolower($file->getFilename()), '.php')) continue;
	if ($file->getSize() > 2000000) continue;
	$txt = file_get_contents($file->getPathname());
	if (strpos($txt, 'PREPARE_EDITOR_HTML') === false) continue;
	echo substr($file->getPathname(), strlen($_SERVER['DOCUMENT_ROOT'])), "\n";
	$hits++;
	if ($hits >= 8) break;
}
echo "hits=$hits\n";
