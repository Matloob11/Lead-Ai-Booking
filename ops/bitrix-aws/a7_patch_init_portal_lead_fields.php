<?php
/**
 * Wire a7_portal_lead_fields.php into bitrix/php_interface/init.php (idempotent).
 */
declare(strict_types=1);

$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$module = '/home/bitrix/www/bitrix/php_interface/include/a7_portal_lead_fields.php';
if (!is_file($module)) {
	fwrite(STDERR, "missing module $module\n");
	exit(1);
}
if (!is_file($init)) {
	fwrite(STDERR, "missing init.php\n");
	exit(1);
}

$marker = 'A7_PORTAL_LEAD_FIELDS';
$block = <<<'PHP'
// A7_PORTAL_LEAD_FIELDS: portal lead details tidy + create-field admin password.
if (is_file(__DIR__ . '/include/a7_portal_lead_fields.php')) {
	require_once __DIR__ . '/include/a7_portal_lead_fields.php';
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
	fwrite(STDERR, "cannot read init.php\n");
	exit(1);
}

if (str_contains($src, $marker) && str_contains($src, 'a7_portal_lead_fields.php')) {
	echo "init already wired\n";
} else {
	$backup = '/home/bitrix/a7_init_bak_portal_lead_fields_' . date('Ymd_His') . '.php';
	if (!copy($init, $backup)) {
		fwrite(STDERR, "backup failed\n");
		exit(1);
	}
	$anchor = '// A7_STAGE_ADMIN:';
	$pos = strpos($src, $anchor);
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
	$tmp = $init . '.tmp_plf';
	file_put_contents($tmp, $patched);
	exec('php -l ' . escapeshellarg($tmp) . ' 2>&1', $out, $code);
	if ($code !== 0) {
		@unlink($tmp);
		fwrite(STDERR, "lint failed:\n" . implode("\n", $out) . "\n");
		exit(1);
	}
	rename($tmp, $init);
	@chmod($init, 0644);
	echo "init wired (backup $backup)\n";
}

exec('php -l ' . escapeshellarg($module) . ' 2>&1', $lint, $lc);
echo implode("\n", $lint) . "\n";
if ($lc !== 0) {
	exit(1);
}

// Prove class registers
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
require_once $module;
echo 'version=', A7PortalLeadFields::VERSION, "\n";
echo 'portal_sources=', count(A7PortalLeadFields::PORTAL_SOURCES), "\n";
echo 'hide=', count(A7PortalLeadFields::HIDE_FIELDS), "\n";

// Sample a recent portal lead
$conn = \Bitrix\Main\Application::getConnection();
$row = $conn->query(
	"SELECT ID, SOURCE_ID FROM b_crm_lead
	 WHERE SOURCE_ID IN ('UC_KQ0WO3','UC_Y3VNS9','UC_BUIJB2','UC_D83356','UC_4FVN3G','UC_PCVWT4','UC_6R3AM9','UC_LX9888','UC_JPSVQU')
	 ORDER BY ID DESC LIMIT 1"
)->fetch();
if ($row) {
	echo 'sample_lead=', $row['ID'], ' source=', $row['SOURCE_ID'], "\n";
	$_SERVER['REQUEST_URI'] = '/crm/lead/details/' . $row['ID'] . '/';
	$boot = A7PortalLeadFields::bootPayload();
	echo 'boot_isPortal=', ($boot['isPortal'] ? 'yes' : 'no'), "\n";
	echo 'boot_lockCreate=', ($boot['lockCreate'] ? 'yes' : 'no'), "\n";
}

foreach (['/bitrix/js/a7_portal_lead_fields.js', '/bitrix/css/a7_portal_lead_fields.css', '/bitrix/js/a7_call_intelligence_crm.js'] as $path) {
	$code = trim((string)shell_exec(
		'curl -sk -o /dev/null -w "%{http_code}" -H "Host: crm.a7grouprealestatedxb.com" '
		. escapeshellarg('https://127.0.0.1' . $path . '?t=' . time())
	));
	$sum = trim((string)shell_exec('md5sum ' . escapeshellarg('/home/bitrix/www' . $path)));
	echo "http $path -> $code | $sum\n";
}

echo "OK\n";
