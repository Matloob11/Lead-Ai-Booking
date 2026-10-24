<?php
/**
 * Wire a7_inventory_webhook.php into bitrix/php_interface/init.php (idempotent).
 * CLI only. Stub after use.
 */
if (PHP_SAPI !== 'cli') {
	http_response_code(404);
	exit(1);
}

$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$module = '/home/bitrix/www/bitrix/php_interface/include/a7_inventory_webhook.php';
if (!is_file($module)) {
	fwrite(STDERR, "missing module\n");
	exit(1);
}
if (!is_file($init)) {
	fwrite(STDERR, "missing init.php\n");
	exit(1);
}

$marker = 'A7_INVENTORY_WEBHOOK';
$block = <<<'PHP'
// A7_INVENTORY_WEBHOOK: ping Lead AI inventory on Availability card changes (C46; off until config enabled).
if (is_file(__DIR__ . '/include/a7_inventory_webhook.php')) {
	require_once __DIR__ . '/include/a7_inventory_webhook.php';
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
	fwrite(STDERR, "cannot read init.php\n");
	exit(1);
}
if (str_contains($src, $marker) && str_contains($src, 'a7_inventory_webhook.php')) {
	echo "init already wired\n";
	exit(0);
}
$backup = '/tmp/a7_init_bak_inventory_webhook_' . date('Ymd_His') . '.php';
if (!copy($init, $backup)) {
	fwrite(STDERR, "backup failed\n");
	exit(1);
}
echo "backup\t{$backup}\n";
$patched = rtrim($src) . "\n" . $block . "\n";
$tmp = $init . '.tmp_inv_wh';
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
echo "DONE\n";
