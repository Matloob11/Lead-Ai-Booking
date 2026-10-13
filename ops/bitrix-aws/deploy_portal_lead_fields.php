<?php
/**
 * Publish portal lead-fields layout + create-field lock, wire init.php.
 * Run on the Lightsail box as bitrix:
 *   sudo -u bitrix php /home/bitrix/www/local/php_interface/include/a7_deploy_portal_lead_fields.php
 *
 * This file is copied to that path as a7_deploy_portal_lead_fields.php before run.
 */
declare(strict_types=1);

$doc = '/home/bitrix/www';
$repo = getenv('A7_REPO_BITRIX') ?: '';
// When run via ops/bitrix.sh run, sources are already put next to this script… but
// we deploy from the same directory the put command wrote into /tmp then copied.
// Simpler: read siblings from DOCUMENT_ROOT after put, OR from include staging.

function fail(string $msg): void
{
	fwrite(STDERR, $msg . "\n");
	exit(1);
}

$backupDir = '/home/bitrix/a7_portal_lead_fields_bak_' . date('Ymd_His');
if (!mkdir($backupDir, 0755, true) && !is_dir($backupDir)) {
	fail("cannot create backup dir $backupDir");
}

$pairs = [
	// local staging names (this script's directory when put as a7_deploy_…)
];

// Sources: same folder as this script (local/php_interface/include) after put,
// falling back to /tmp copies named explicitly.
$here = __DIR__;
$sources = [
	$doc . '/bitrix/php_interface/include/a7_portal_lead_fields.php' => null, // may not exist yet
];

$map = [
	'a7_portal_lead_fields.php' => $doc . '/bitrix/php_interface/include/a7_portal_lead_fields.php',
	'a7_portal_lead_fields.js' => $doc . '/bitrix/js/a7_portal_lead_fields.js',
	'a7_portal_lead_fields.css' => $doc . '/bitrix/css/a7_portal_lead_fields.css',
	'a7_call_intelligence_crm.js' => $doc . '/bitrix/js/a7_call_intelligence_crm.js',
];

// Prefer files staged beside this deploy script under include/, else /tmp/a7-plf-*
foreach ($map as $name => $dst) {
	$candidates = [
		$here . '/' . $name,
		'/tmp/a7-plf-' . $name,
		$doc . '/local/php_interface/include/' . $name,
	];
	$src = null;
	foreach ($candidates as $c) {
		if (is_file($c)) {
			$src = $c;
			break;
		}
	}
	if ($src === null) {
		// call_intelligence may already be live; skip if not staged
		if ($name === 'a7_call_intelligence_crm.js' && is_file($dst)) {
			echo "skip $name (not staged; live kept)\n";
			continue;
		}
		fail("missing source for $name");
	}
	if (is_file($dst)) {
		copy($dst, $backupDir . '/' . basename($dst));
	}
	$dir = dirname($dst);
	if (!is_dir($dir) && !mkdir($dir, 0755, true) && !is_dir($dir)) {
		fail("cannot mkdir $dir");
	}
	if (!copy($src, $dst)) {
		fail("copy failed $src -> $dst");
	}
	@chmod($dst, 0644);
	@chown($dst, 'bitrix');
	@chgrp($dst, 'bitrix');
	echo 'deployed ' . basename($dst) . ' ' . filesize($dst) . ' ' . md5_file($dst) . "\n";
}

$init = $doc . '/bitrix/php_interface/init.php';
$marker = 'A7_PORTAL_LEAD_FIELDS';
$block = <<<'PHP'
// A7_PORTAL_LEAD_FIELDS: portal lead details tidy + create-field admin password.
if (is_file(__DIR__ . '/include/a7_portal_lead_fields.php')) {
	require_once __DIR__ . '/include/a7_portal_lead_fields.php';
}
PHP;

$srcInit = file_get_contents($init);
if ($srcInit === false) {
	fail('cannot read init.php');
}

if (str_contains($srcInit, $marker) && str_contains($srcInit, 'a7_portal_lead_fields.php')) {
	echo "init block already present\n";
} else {
	// Insert after A7_STAGE_ADMIN block when present, else append.
	$anchor = "// A7_STAGE_ADMIN:";
	$pos = strpos($srcInit, $anchor);
	if ($pos !== false) {
		// find end of that require block (next blank line after require_once)
		$after = strpos($srcInit, "\n\n", $pos);
		if ($after === false) {
			$patched = rtrim($srcInit) . "\n" . $block . "\n";
		} else {
			$patched = substr($srcInit, 0, $after) . "\n" . $block . substr($srcInit, $after);
		}
	} else {
		$patched = rtrim($srcInit) . "\n" . $block . "\n";
	}
	$tmp = $init . '.tmp_portal_lead_fields';
	if (file_put_contents($tmp, $patched) === false) {
		fail('write init temp failed');
	}
	exec('php -l ' . escapeshellarg($tmp) . ' 2>&1', $out, $code);
	if ($code !== 0) {
		@unlink($tmp);
		fail("patched init.php does not lint — left untouched:\n" . implode("\n", $out));
	}
	copy($init, $backupDir . '/init.php');
	if (!rename($tmp, $init)) {
		fail('init.php replace failed');
	}
	@chown($init, 'bitrix');
	@chgrp($init, 'bitrix');
	echo "init block added (backup in $backupDir)\n";
}

// Prove public assets
foreach (['/bitrix/js/a7_portal_lead_fields.js', '/bitrix/css/a7_portal_lead_fields.css'] as $path) {
	$code = trim((string)shell_exec(
		'curl -sk -o /dev/null -w "%{http_code}" -H "Host: crm.a7grouprealestatedxb.com" '
		. escapeshellarg('https://127.0.0.1' . $path . '?t=' . time())
	));
	echo "http $path -> $code\n";
}

// php -l module
exec('php -l ' . escapeshellarg($doc . '/bitrix/php_interface/include/a7_portal_lead_fields.php') . ' 2>&1', $lintOut, $lintCode);
echo implode("\n", $lintOut) . "\n";
if ($lintCode !== 0) {
	fail('module lint failed');
}

echo "OK portal lead fields deploy\n";
