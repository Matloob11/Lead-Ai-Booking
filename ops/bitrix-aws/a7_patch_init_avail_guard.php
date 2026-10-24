<?php
/**
 * Wire a7_avail_guard.php into bitrix/php_interface/init.php (idempotent).
 * Run once on the box via: ops/bitrix.sh run a7_patch_init_avail_guard.php
 * (file must already be at include/a7_avail_guard.php)
 */
if (PHP_SAPI !== 'cli') {
	http_response_code(404);
	exit(1);
}

$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$module = '/home/bitrix/www/bitrix/php_interface/include/a7_avail_guard.php';
if (!is_file($module)) {
	fwrite(STDERR, "missing module\n");
	exit(1);
}
if (!is_file($init)) {
	fwrite(STDERR, "missing init.php\n");
	exit(1);
}

$marker = 'A7_AVAIL_GUARD';
$block = <<<'PHP'
// A7_AVAIL_GUARD: refuse incomplete Owner Data cards in Rent/Sale Availability stages (C55).
if (is_file(__DIR__ . '/include/a7_avail_guard.php')) {
	require_once __DIR__ . '/include/a7_avail_guard.php';
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
	fwrite(STDERR, "cannot read init.php\n");
	exit(1);
}
if (str_contains($src, $marker) && str_contains($src, 'a7_avail_guard.php')) {
	echo "init already wired\n";
} else {
	$backup = '/tmp/a7_init_bak_avail_guard_' . date('Ymd_His') . '.php';
	if (!copy($init, $backup)) {
		fwrite(STDERR, "backup failed\n");
		exit(1);
	}
	echo "backup\t", $backup, "\n";
	$patched = rtrim($src) . "\n" . $block . "\n";
	$tmp = $init . '.tmp_avail_guard';
	file_put_contents($tmp, $patched);
	exec('php -l ' . escapeshellarg($tmp) . ' 2>&1', $out, $code);
	if ($code !== 0) {
		@unlink($tmp);
		fwrite(STDERR, "lint failed\n" . implode("\n", $out) . "\n");
		exit(1);
	}
	if (!rename($tmp, $init)) {
		@unlink($tmp);
		fwrite(STDERR, "init.php replace failed\n");
		exit(1);
	}
	@chmod($init, 0644);
	echo "init wired\n";
}
exec('php -l ' . escapeshellarg($module) . ' 2>&1', $lint, $lc);
echo implode("\n", $lint), "\n";
echo "version\t", defined('A7_AVAIL_GUARD_LOADED') ? 'loaded-at-lint' : 'file-ok', "\n";
exit($lc === 0 ? 0 : 1);
