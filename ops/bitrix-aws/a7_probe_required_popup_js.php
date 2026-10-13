<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$root = $_SERVER['DOCUMENT_ROOT'];
$needles = [
	'CRM_KANBAN_REQUIRED_FIELDS_TITLE_LEAD',
	'required fields to change lead',
	'PartialEditorDialog',
	'showRequiredFields',
];
foreach ($needles as $n) {
	echo "=== $n ===\n";
	passthru('grep -R -l -n ' . escapeshellarg($n) . ' ' . escapeshellarg($root . '/bitrix/js/crm') . ' ' . escapeshellarg($root . '/bitrix/modules/crm/install/js') . ' 2>/dev/null | head -15');
}
echo "=== lang exact ===\n";
passthru('grep -n "LEAD STAGE\\|lead stage\\|REQUIRED_FIELDS_TITLE" ' . escapeshellarg($root . '/bitrix/modules/crm/lang/en/kanban.php'));
passthru('grep -R -n "to change lead" ' . escapeshellarg($root . '/bitrix/modules/crm/lang/en') . ' 2>/dev/null | head -20');
