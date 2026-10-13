<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$root = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/js/crm';
$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS));
$hits = 0;
foreach ($it as $file) {
	if (!$file->isFile()) continue;
	$name = $file->getFilename();
	if (!preg_match('/\.(js|map)$/', $name)) continue;
	if ($file->getSize() > 4000000) continue;
	$txt = file_get_contents($file->getPathname());
	if (strpos($txt, 'PartialEditorDialog = function') !== false || strpos($txt, 'PartialEditorDialog.prototype.open') !== false) {
		echo substr($file->getPathname(), strlen($_SERVER['DOCUMENT_ROOT'])), " size=", $file->getSize(), "\n";
		$hits++;
		if ($hits >= 8) break;
	}
}
echo "hits=$hits\n";
