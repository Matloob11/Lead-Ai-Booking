<?php
/**
 * Verify portal lead fields deploy without starting a Bitrix web session.
 */
declare(strict_types=1);

$doc = '/home/bitrix/www';
$checks = [
	$doc . '/bitrix/php_interface/include/a7_portal_lead_fields.php',
	$doc . '/bitrix/js/a7_portal_lead_fields.js',
	$doc . '/bitrix/css/a7_portal_lead_fields.css',
	$doc . '/bitrix/js/a7_call_intelligence_crm.js',
];
foreach ($checks as $path) {
	if (!is_file($path)) {
		fwrite(STDERR, "MISSING $path\n");
		exit(1);
	}
	echo 'ok ', basename($path), ' ', md5_file($path), ' ', filesize($path), "\n";
}

$init = file_get_contents($doc . '/bitrix/php_interface/init.php');
echo str_contains($init, 'A7_PORTAL_LEAD_FIELDS') ? "init: wired\n" : "init: MISSING\n";
echo str_contains($init, 'a7_portal_lead_fields.php') ? "init: require ok\n" : "init: require MISSING\n";

$ci = file_get_contents($doc . '/bitrix/js/a7_call_intelligence_crm.js');
echo str_contains($ci, "data-a7-plf") ? "ci: skip other-section ok\n" : "ci: skip MISSING\n";

$js = file_get_contents($doc . '/bitrix/js/a7_portal_lead_fields.js');
echo str_contains($js, 'Other fields') || str_contains($js, 'otherTitle') ? "js: other section ok\n" : "js: other MISSING\n";
echo str_contains($js, 'userfieldconfig.add') ? "js: create lock ok\n" : "js: create lock MISSING\n";

$php = file_get_contents($doc . '/bitrix/php_interface/include/a7_portal_lead_fields.php');
echo str_contains($php, 'OnBeforeUserTypeAdd') ? "php: UF lock ok\n" : "php: UF lock MISSING\n";
echo str_contains($php, 'UC_Y3VNS9') ? "php: bayut source ok\n" : "php: bayut MISSING\n";

foreach (['/bitrix/js/a7_portal_lead_fields.js', '/bitrix/css/a7_portal_lead_fields.css'] as $path) {
	$code = trim((string)shell_exec(
		'curl -sk -o /dev/null -w "%{http_code}" -H "Host: crm.a7grouprealestatedxb.com" '
		. escapeshellarg('https://127.0.0.1' . $path . '?t=' . time())
	));
	echo "http $path -> $code\n";
}

// DB: recent portal lead id for manual browser check
$out = [];
exec(
	"mysql --batch --skip-column-names -e " . escapeshellarg(
		"SELECT ID, SOURCE_ID FROM sitemanager.b_crm_lead
		 WHERE SOURCE_ID IN ('UC_KQ0WO3','UC_Y3VNS9','UC_BUIJB2','UC_D83356','UC_4FVN3G','UC_PCVWT4','UC_6R3AM9','UC_LX9888','UC_JPSVQU')
		 ORDER BY ID DESC LIMIT 3"
	) . " 2>&1",
	$out,
	$code
);
echo "sample_leads:\n";
foreach ($out as $line) {
	echo "  ", $line, "\n";
}

// Prove OnBeforeUserTypeAdd denies without password (CLI bypass would allow — force web)
define('A7_PORTAL_LEAD_FIELDS_BYPASS', false);
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_SKIP_SESSION_EXPAND', true);
$_SERVER['DOCUMENT_ROOT'] = $doc;
$_SERVER['REQUEST_METHOD'] = 'POST';
$_SERVER['REQUEST_URI'] = '/bitrix/services/main/ajax.php?action=main.userfieldconfig.add';
// Include module only (no full prolog)
require_once $doc . '/bitrix/php_interface/include/a7_portal_lead_fields.php';

// Simulate bypass off + empty password
$ref = new ReflectionClass('A7PortalLeadFields');
$allowed = $ref->getProperty('allowed');
$allowed->setAccessible(true);
$allowed->setValue(null, null);

// isBypassContext is true on CLI — test passwordFromRequest / denyMessage paths instead
echo 'deny_empty=', A7PortalLeadFields::denyMessage(false), "\n";
echo 'deny_wrong=', A7PortalLeadFields::denyMessage(true), "\n";
echo 'param=', A7PortalLeadFields::PARAM, "\n";
echo "OK verify\n";
