<?php
/**
 * WhatsApp Leads (UC_WA_LEADS):
 *   details (comment / bedrooms / client type / community) → AI Qualified (12)
 *   blank → Junk (JUNK)
 * Then delete the WhatsApp Leads status.
 *
 * APPLY=0 (default): print plan only.
 * APPLY=1: move + delete stage.
 *
 * Automation / live feed / timeline comments stay off so junking
 * ~300 cards does not fire robots or n8n.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$apply = getenv('APPLY') === '1';
$from = 'UC_WA_LEADS';
$toDetails = '12';
$toBlank = 'JUNK';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
	fwrite(STDERR, "db fail\n");
	exit(2);
}

$cols = [];
$q = $m->query(
	"SELECT f.FIELD_NAME
	 FROM b_user_field f
	 LEFT JOIN b_user_field_lang l ON l.USER_FIELD_ID=f.ID AND l.LANGUAGE_ID='en'
	 WHERE f.ENTITY_ID='CRM_LEAD'
	   AND (
	     l.EDIT_FORM_LABEL LIKE '%Bedroom%'
	     OR l.EDIT_FORM_LABEL LIKE '%Community%'
	     OR l.EDIT_FORM_LABEL LIKE '%Client Type%'
	     OR l.EDIT_FORM_LABEL LIKE '%Client type%'
	   )"
);
while ($r = $q->fetch_assoc()) {
	$cols[] = $r['FIELD_NAME'];
}

$parts = ["TRIM(COALESCE(l.COMMENTS,'')) <> ''"];
foreach ($cols as $col) {
	$parts[] = "(u.`$col` IS NOT NULL AND TRIM(CAST(u.`$col` AS CHAR)) <> '' AND CAST(u.`$col` AS CHAR) NOT IN ('0','a:0:{}'))";
}
$detailSql = implode(' OR ', $parts);
$fromSql = "'" . $m->real_escape_string($from) . "'";

function fetchIds(mysqli $m, string $sql): array
{
	$ids = [];
	$q = $m->query($sql);
	if (!$q) {
		fwrite(STDERR, "query fail " . $m->error . "\n");
		exit(2);
	}
	while ($r = $q->fetch_assoc()) {
		$ids[] = (int)$r['ID'];
	}
	return $ids;
}

$detailIds = fetchIds(
	$m,
	"SELECT l.ID FROM b_crm_lead l
	 LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
	 WHERE l.STATUS_ID=$fromSql AND ($detailSql)
	 ORDER BY l.ID"
);
$blankIds = fetchIds(
	$m,
	"SELECT l.ID FROM b_crm_lead l
	 LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
	 WHERE l.STATUS_ID=$fromSql AND NOT ($detailSql)
	 ORDER BY l.ID"
);

$stages = [];
$q = $m->query("SELECT ID, STATUS_ID, NAME, SORT, SEMANTICS FROM b_crm_status WHERE ENTITY_ID='STATUS' AND STATUS_ID IN ('$from','$toDetails','$toBlank')");
while ($r = $q->fetch_assoc()) {
	$stages[$r['STATUS_ID']] = $r;
}

echo "apply=" . ($apply ? 'yes' : 'no') . "\n";
echo "card_fields=" . implode(',', $cols) . "\n";
echo "from=$from name=" . ($stages[$from]['NAME'] ?? 'MISSING') . " row_id=" . ($stages[$from]['ID'] ?? '') . "\n";
echo "to_details=$toDetails name=" . ($stages[$toDetails]['NAME'] ?? 'MISSING') . "\n";
echo "to_blank=$toBlank name=" . ($stages[$toBlank]['NAME'] ?? 'MISSING') . "\n";
echo "detail_count=" . count($detailIds) . "\n";
echo "blank_count=" . count($blankIds) . "\n";
echo "total_in_stage=" . (count($detailIds) + count($blankIds)) . "\n";

echo "=== detail titles ===\n";
if ($detailIds) {
	$in = implode(',', $detailIds);
	$q = $m->query("SELECT ID, TITLE FROM b_crm_lead WHERE ID IN ($in) ORDER BY ID");
	while ($r = $q->fetch_assoc()) {
		echo $r['ID'] . "\t" . $r['TITLE'] . "\n";
	}
}

echo "=== robots / bp on these stages ===\n";
$tables = [];
$tq = $m->query("SHOW TABLES");
while ($r = $tq->fetch_row()) {
	$tables[$r[0]] = true;
}
if (!empty($tables['b_crm_automation_trigger'])) {
	$q = $m->query(
		"SELECT ID, ENTITY_TYPE_ID, ENTITY_STATUS, CODE
		 FROM b_crm_automation_trigger
		 WHERE ENTITY_TYPE_ID=1
		   AND ENTITY_STATUS IN ('$from','$toDetails','$toBlank')"
	);
	$n = 0;
	if ($q) {
		while ($r = $q->fetch_assoc()) {
			echo "trigger " . json_encode($r) . "\n";
			$n++;
		}
	}
	echo "trigger_rows=$n\n";
}
if (!empty($tables['b_bp_workflow_template'])) {
	$q = $m->query(
		"SELECT ID, NAME, DOCUMENT_STATUS
		 FROM b_bp_workflow_template
		 WHERE MODULE_ID='crm' AND ENTITY='CCrmDocumentLead'
		   AND (
		     DOCUMENT_STATUS LIKE '%$from%'
		     OR DOCUMENT_STATUS LIKE '%\"$toDetails\"%'
		     OR DOCUMENT_STATUS LIKE '%$toBlank%'
		   )"
	);
	$n = 0;
	if ($q) {
		while ($r = $q->fetch_assoc()) {
			echo "bp " . $r['ID'] . "\t" . $r['NAME'] . "\t" . $r['DOCUMENT_STATUS'] . "\n";
			$n++;
		}
	}
	echo "bp_rows=$n\n";
}

if (!$apply) {
	echo "DRY_RUN\n";
	exit(0);
}

if (empty($stages[$from]) || empty($stages[$toDetails]) || empty($stages[$toBlank])) {
	fwrite(STDERR, "missing status row\n");
	exit(1);
}

\Bitrix\Main\Loader::includeModule('crm');
global $USER;
if (is_object($USER)) {
	$USER->Authorize(1);
}

function moveLeads(array $ids, string $status): array
{
	$crmLead = new CCrmLead(false);
	$ok = 0;
	$fail = 0;
	foreach ($ids as $id) {
		$fields = ['STATUS_ID' => $status];
		$options = [
			'CURRENT_USER' => 1,
			'REGISTER_SONET_EVENT' => false,
			'ENABLE_SYSTEM_EVENTS' => false,
		];
		$res = $crmLead->Update($id, $fields, true, true, $options);
		if ($res) {
			$ok++;
		} else {
			$fail++;
			$ex = $GLOBALS['APPLICATION']->GetException();
			echo "FAIL lead=$id " . ($ex ? $ex->GetString() : 'unknown') . "\n";
		}
	}
	return [$ok, $fail];
}

echo "=== moving details -> $toDetails ===\n";
[$dOk, $dFail] = moveLeads($detailIds, $toDetails);
echo "details_ok=$dOk details_fail=$dFail\n";

echo "=== moving blank -> $toBlank ===\n";
[$bOk, $bFail] = moveLeads($blankIds, $toBlank);
echo "blank_ok=$bOk blank_fail=$bFail\n";

$left = (int)$m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE STATUS_ID=$fromSql")->fetch_assoc()['c'];
echo "left_in_wa_stage=$left\n";

$afterDetails = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_lead WHERE ID IN (" . ($detailIds ? implode(',', $detailIds) : '0') . ") AND STATUS_ID='" . $m->real_escape_string($toDetails) . "'"
)->fetch_assoc()['c'];
$afterBlank = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_lead WHERE ID IN (" . ($blankIds ? implode(',', $blankIds) : '0') . ") AND STATUS_ID='" . $m->real_escape_string($toBlank) . "'"
)->fetch_assoc()['c'];
echo "prove_details_in_ai=$afterDetails\n";
echo "prove_blank_in_junk=$afterBlank\n";

if ($left !== 0 || $dFail || $bFail) {
	echo "SKIP_DELETE stage not empty or update failed\n";
	exit(1);
}

$rowId = (int)$stages[$from]['ID'];
echo "=== delete status row $rowId $from ===\n";
$crmStatus = new CCrmStatus('STATUS');
$del = $crmStatus->Delete($rowId);
echo "delete_ok=" . ($del ? 'yes' : 'no') . "\n";
if (!$del) {
	$ex = $GLOBALS['APPLICATION']->GetException();
	echo "delete_err=" . ($ex ? $ex->GetString() : 'unknown') . "\n";
	exit(1);
}

$gone = $m->query("SELECT ID, STATUS_ID, NAME FROM b_crm_status WHERE ENTITY_ID='STATUS' AND STATUS_ID=$fromSql");
echo "status_still_there=" . ($gone && $gone->num_rows ? 'yes' : 'no') . "\n";

if (!empty($tables['b_bp_workflow_template'])) {
	$q = $m->query(
		"SELECT ID, NAME, DOCUMENT_STATUS FROM b_bp_workflow_template
		 WHERE MODULE_ID='crm' AND ENTITY='CCrmDocumentLead'
		   AND DOCUMENT_STATUS LIKE '%$from%'"
	);
	while ($q && ($r = $q->fetch_assoc())) {
		echo "orphan_bp=" . $r['ID'] . "\t" . $r['NAME'] . "\t" . $r['DOCUMENT_STATUS'] . "\n";
	}
}
echo "DONE\n";
