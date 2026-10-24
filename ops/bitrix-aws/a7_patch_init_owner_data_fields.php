<?php
/**
 * Wire a7_owner_data_fields.php into bitrix/php_interface/init.php (idempotent).
 */
declare(strict_types=1);

$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$module = '/home/bitrix/www/bitrix/php_interface/include/a7_owner_data_fields.php';

if (!is_file($module)) {
	fwrite(STDERR, "missing module $module\n");
	exit(1);
}
if (!is_file($init)) {
	fwrite(STDERR, "missing init.php\n");
	exit(1);
}

$marker = 'A7_OWNER_DATA_FIELDS';
$block = <<<'PHP'
// A7_OWNER_DATA_FIELDS: Owner Data (SPA 1042 / CRM_5) field create/change/select/hide password.
if (is_file(__DIR__ . '/include/a7_owner_data_fields.php')) {
	require_once __DIR__ . '/include/a7_owner_data_fields.php';
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
	fwrite(STDERR, "cannot read init.php\n");
	exit(1);
}

if (str_contains($src, $marker) && str_contains($src, 'a7_owner_data_fields.php')) {
	echo "init already wired\n";
} else {
	$backup = '/home/bitrix/a7_init_bak_owner_data_fields_' . date('Ymd_His') . '.php';
	if (!copy($init, $backup)) {
		fwrite(STDERR, "backup failed\n");
		exit(1);
	}
	$anchor = '// A7_PORTAL_LEAD_FIELDS:';
	$pos = strpos($src, $anchor);
	if ($pos === false) {
		$anchor = '// A7_STAGE_ADMIN:';
		$pos = strpos($src, $anchor);
	}
	if ($pos !== false) {
		$after = strpos($src, "\n\n", $pos);
		if ($after === false) {
			$patched = rtrim($src) . "\n" . $block . "\n";
		} else {
			$patched = substr($src, 0, $after) . "\n" . $block . substr($src, $after);
		}
	} else {
		$patched = rtrim($src) . "\n" . $block . "\n";
	}
	$tmp = $init . '.tmp_odf';
	file_put_contents($tmp, $patched);
	exec('php -l ' . escapeshellarg($tmp) . ' 2>&1', $out, $code);
	if ($code !== 0) {
		@unlink($tmp);
		fwrite(STDERR, "lint failed:\n" . implode("\n", $out) . "\n");
		exit(1);
	}
	rename($tmp, $init);
	@chmod($init, 0644);
	@chown($init, 'bitrix');
	@chgrp($init, 'bitrix');
	echo "init wired (backup $backup)\n";
}

exec('php -l ' . escapeshellarg($module) . ' 2>&1', $lint, $lc);
echo implode("\n", $lint) . "\n";
if ($lc !== 0) {
	exit(1);
}

require_once $module;
echo 'version=', A7OwnerDataFields::VERSION, "\n";
echo 'entity=', A7OwnerDataFields::ENTITY_ID, ' type=', A7OwnerDataFields::TYPE_ID, "\n";

foreach (['/bitrix/js/a7_owner_data_fields.js', '/bitrix/css/a7_owner_data_fields.css'] as $path) {
	$code = trim((string)shell_exec(
		'curl -sk -o /dev/null -w "%{http_code}" -H "Host: crm.a7grouprealestatedxb.com" '
		. escapeshellarg('https://127.0.0.1' . $path . '?t=' . time())
	));
	$sum = trim((string)shell_exec('md5sum ' . escapeshellarg('/home/bitrix/www' . $path)));
	echo "http $path -> $code | $sum\n";
}

echo "OK\n";
