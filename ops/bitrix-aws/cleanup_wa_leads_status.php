<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== status list (whatsapp / 12 / JUNK) ===\n";
$q = $m->query("SELECT ID, STATUS_ID, NAME, SORT FROM b_crm_status WHERE ENTITY_ID='STATUS' ORDER BY SORT");
$hasWa = false;
while ($r = $q->fetch_assoc()) {
	if (stripos($r['NAME'], 'whatsapp') !== false || $r['STATUS_ID'] === 'UC_WA_LEADS' || $r['STATUS_ID'] === '12' || $r['STATUS_ID'] === 'JUNK') {
		echo $r['STATUS_ID'] . "\t" . $r['NAME'] . "\t" . $r['SORT'] . "\n";
	}
	if ($r['STATUS_ID'] === 'UC_WA_LEADS' || stripos($r['NAME'], 'WhatsApp Leads') !== false) {
		$hasWa = true;
	}
}
echo "wa_stage_present=" . ($hasWa ? 'yes' : 'no') . "\n";

$ids = [69916, 71305, 73512, 73471];
echo "=== sample lead statuses ===\n";
$q = $m->query("SELECT ID, TITLE, STATUS_ID FROM b_crm_lead WHERE ID IN (" . implode(',', $ids) . ")");
while ($r = $q->fetch_assoc()) {
	echo $r['ID'] . "\t" . $r['STATUS_ID'] . "\t" . $r['TITLE'] . "\n";
}

echo "=== leftover in UC_WA_LEADS ===\n";
$left = (int)$m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE STATUS_ID='UC_WA_LEADS'")->fetch_assoc()['c'];
echo "left=$left\n";

$bpId = 374;
$q = $m->query("SELECT ID, NAME, DOCUMENT_STATUS FROM b_bp_workflow_template WHERE ID=$bpId");
$row = $q ? $q->fetch_assoc() : null;
echo "orphan_bp=" . json_encode($row) . "\n";

if ($row && $row['DOCUMENT_STATUS'] === 'UC_WA_LEADS') {
	\Bitrix\Main\Loader::includeModule('bizproc');
	CBPWorkflowTemplateLoader::Delete($bpId);
	$again = $m->query("SELECT ID FROM b_bp_workflow_template WHERE ID=$bpId");
	echo "orphan_bp_deleted=" . ($again && $again->num_rows ? 'no' : 'yes') . "\n";
} else {
	echo "orphan_bp_deleted=skip\n";
}

echo "DONE\n";
