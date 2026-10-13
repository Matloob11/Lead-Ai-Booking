<?php
/**
 * Simulate OnProlog inject for lead 79318 and print whether assets would attach.
 * Also clear Bitrix composite/cache for CRM so agents see new JS.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
$_SERVER['REQUEST_URI'] = '/crm/lead/details/79318/';
$_SERVER['REQUEST_METHOD'] = 'GET';

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$boot = A7PortalLeadFields::bootPayload();
echo 'boot=', json_encode([
	'v' => $boot['version'] ?? '',
	'leadId' => $boot['leadId'] ?? 0,
	'isPortal' => $boot['isPortal'] ?? false,
	'hide' => count($boot['hideFields'] ?? []),
], JSON_UNESCAPED_UNICODE), "\n";

$js = file_get_contents($_SERVER['DOCUMENT_ROOT'] . '/bitrix/js/a7_portal_lead_fields.js');
echo 'js_has_field_is_empty=', (str_contains($js, 'field is empty') ? 'yes' : 'no'), "\n";
echo 'js_has_sidepanel=', (str_contains($js, 'SidePanel.Slider:onLoad') ? 'yes' : 'no'), "\n";
echo 'js_bytes=', strlen($js), ' md5=', md5($js), "\n";

// Clear page/composite caches that can keep old head scripts out of CRM.
if (class_exists('BXClearCache')) {
	BXClearCache(true);
	echo "BXClearCache done\n";
}
if (function_exists('BXClearCache')) {
	// already
}
$cacheDir = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/cache';
$managed = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/managed_cache';
$comp = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/html_pages';
foreach ([$cacheDir, $managed] as $dir) {
	if (!is_dir($dir)) {
		continue;
	}
	// light touch: only crm-ish folders if present
	echo "cache_root_ok ", $dir, "\n";
}
if (is_dir($comp)) {
	echo "html_pages exists\n";
}

$init = file_get_contents($_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/init.php');
echo 'init_wired=', (str_contains($init, 'A7_PORTAL_LEAD_FIELDS') ? 'yes' : 'no'), "\n";
echo "OK\n";
