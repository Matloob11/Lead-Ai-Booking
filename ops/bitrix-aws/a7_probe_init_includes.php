<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$init = file_get_contents($_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/init.php');
foreach (['a7_stage_admin', 'a7_lead_guard', 'a7_call_intelligence', 'a7_portal_lead'] as $name) {
	echo $name, ': ', (str_contains($init, $name) ? 'yes' : 'no'), "\n";
}
echo "--- stage_admin require lines ---\n";
foreach (preg_split('/\R/', $init) as $i => $line) {
	if (stripos($line, 'a7_stage_admin') !== false || stripos($line, 'a7_lead_guard') !== false) {
		echo ($i + 1), ': ', trim($line), "\n";
	}
}
