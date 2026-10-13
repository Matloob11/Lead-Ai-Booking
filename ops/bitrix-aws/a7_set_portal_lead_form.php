<?php
/**
 * Rebuild the common Lead details form so Bayut / PF / Dubizzle card fields
 * (Community, Bedrooms, Client Type, Sub Community, Deal Amount, …) are
 * selected on the details page — not only on the kanban card.
 *
 * Backs up the previous common option, then writes a clean layout:
 *   1) Portal details — filled/useful fields
 *   2) Responsible
 *   3) Other fields — Call Recording + rarely-used empties
 *
 * Extra phone UFs are removed from the form (system PHONE stays).
 */
declare(strict_types=1);

$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('ui');

$conn = \Bitrix\Main\Application::getConnection();

function field(string $name): array
{
	return ['name' => $name, 'optionFlags' => '1'];
}

function section(string $name, string $title, array $fields): array
{
	$elements = [];
	foreach ($fields as $f) {
		$elements[] = is_string($f) ? field($f) : $f;
	}
	return [
		'name' => $name,
		'title' => $title,
		'type' => 'section',
		'elements' => $elements,
	];
}

$portalFields = [
	'NAME',
	'PHONE',
	'SOURCE_ID',
	'UF_CRM_1760707563281', // Property Reference
	'UF_CRM_1760707872553', // Portal Lead ID
	'UF_CRM_1760707550978', // Property Link
	'UF_CRM_1770537051525', // Community (text)
	'UF_CRM_1763390140',    // Community (link — what kanban card shows)
	'UF_CRM_1763390179',    // Sub Community
	'UF_CRM_1731838126127', // No. of Bedrooms
	'UF_CRM_1756638760279', // Client Type (DB label "owner")
	'UF_CRM_1736306439793', // Deal Amount
	'UF_CRM_A7_RENT_SALE',  // Rent / Sale
	'UF_CRM_1770537849303', // Sub Source
	'COMMENTS',
];

$otherFields = [
	'UF_CRM_1765536351834', // Call Recording
	'UF_CRM_A7_AI_COMMUNITY_FLEXIBILITY',
	'UF_CRM_1731838581336', // Budget (Option Sent / Future Prospect / Booking)
	'UF_CRM_1735126982325', // Offering Type
	'UF_CRM_1760707526983', // Permit/DTMC
	'UF_CRM_1740043316741', // Budget Range
	// Required when the stage changes — the stage popup can only draw an input
	// for a field that is on this form.
	'UF_CRM_1761633927',    // Contacted Details
	'UF_CRM_1761633899',    // No Answer Details
	'UF_CRM_1761633956',    // Option Sent Details
	'UF_CRM_1739869968682', // Timeline
	'UF_CRM_1731838813769', // Meeting Date & Time
	'UF_CRM_1758002109',    // Meeting Feedback
	'UF_CRM_1761633993',    // Future Prospect Details
	'UF_CRM_1731838049723', // Project Name
	'UF_CRM_1731838620873', // Expected Date of Booking
	'UF_CRM_1734162646510', // Reason of Reject
	'UF_CRM_1731838640428', // Booking Amount
	'OPPORTUNITY_WITH_CURRENCY',
];

$cfg = [[
	'name' => 'default_column',
	'type' => 'column',
	'elements' => [
		section('a7_portal_details', 'Portal details', $portalFields),
		section('a7_responsible', 'Responsible', ['ASSIGNED_BY_ID', 'OBSERVER']),
		section('a7_other_fields', 'Other fields', $otherFields),
		section('a7_shops_bot', 'Shops bot', [
			'UF_CRM_LEAD_1737031634747',
			'UF_CRM_A7_AI_BUSINESS_ACTIVITY',
			'UF_CRM_A7_AI_TRADE_LICENSE_STATUS',
			'UF_CRM_A7_TRADE_LICENSE_FILE',
			'UF_CRM_A7_SHOP_TYPE',
			'UF_CRM_A7_BOT_STATUS',
			'UF_CRM_A7_WA_OPT_OUT',
		]),
	],
]];

// ---- backup common option ----
$row = $conn->query(
	"SELECT ID, VALUE FROM b_user_option
	 WHERE USER_ID=0 AND CATEGORY='crm.entity.editor' AND NAME='lead_details_common'
	 LIMIT 1"
)->fetch();
if (!$row) {
	fwrite(STDERR, "lead_details_common missing\n");
	exit(1);
}
$backupDir = '/home/bitrix/a7_lead_form_bak_' . date('Ymd_His');
if (!mkdir($backupDir, 0755, true) && !is_dir($backupDir)) {
	fwrite(STDERR, "backup dir failed\n");
	exit(1);
}
file_put_contents($backupDir . '/lead_details_common.ser', $row['VALUE']);
echo "backup $backupDir/lead_details_common.ser (", strlen($row['VALUE']), " bytes)\n";

$serialized = serialize($cfg);

// Prefer Bitrix API so caches clear
if (class_exists('CUserOptions')) {
	\CUserOptions::SetOption('crm.entity.editor', 'lead_details_common', $cfg, true, 0);
	echo "CUserOptions::SetOption lead_details_common OK\n";
} else {
	$conn->queryExecute(
		"UPDATE b_user_option SET VALUE='" . $conn->getSqlHelper()->forSql($serialized) . "'
		 WHERE ID=" . (int)$row['ID']
	);
	echo "SQL update lead_details_common OK\n";
}

// Also refresh named common scope "Portals Lead Details" (ID 2)
$portals = $conn->query(
	"SELECT ID, CONFIG FROM b_ui_entity_editor_config WHERE ID=2 AND ENTITY_TYPE_ID='lead_details'"
)->fetch();
if ($portals) {
	file_put_contents($backupDir . '/portals_lead_details_id2.ser', $portals['CONFIG']);
	$conn->queryExecute(
		"UPDATE b_ui_entity_editor_config
		 SET CONFIG='" . $conn->getSqlHelper()->forSql($serialized) . "',
		     NAME='Portals Lead Details'
		 WHERE ID=2"
	);
	echo "updated b_ui_entity_editor_config ID=2\n";
}

// Admin personal override (USER 1) was hiding the common card fields — align it too
$personal = $conn->query(
	"SELECT ID, VALUE FROM b_user_option
	 WHERE USER_ID=1 AND CATEGORY='crm.entity.editor' AND NAME='lead_details'
	 LIMIT 1"
)->fetch();
if ($personal) {
	file_put_contents($backupDir . '/user1_lead_details.ser', $personal['VALUE']);
	if (class_exists('CUserOptions')) {
		\CUserOptions::SetOption('crm.entity.editor', 'lead_details', $cfg, false, 1);
		echo "aligned USER=1 personal lead_details\n";
	}
}

// Force common scope for all (same idea as REST forceCommonScopeForAll)
try {
	if (class_exists(\Bitrix\Crm\Entity\EntityEditorConfigScope::class)) {
		// best-effort: set scope option for common
	}
	$conn->queryExecute(
		"UPDATE b_user_option
		 SET VALUE='" . $conn->getSqlHelper()->forSql(serialize('C')) . "'
		 WHERE CATEGORY='crm.entity.editor'
		   AND NAME IN ('lead_details_scope','lead_details_scope_on_update','lead_details_scope_on_add')
		   AND USER_ID>0"
	);
	echo "scoped users toward common (C) where those options exist\n";
} catch (\Throwable $e) {
	echo "scope nudge skip: ", $e->getMessage(), "\n";
}

if (function_exists('BXClearCache')) {
	BXClearCache(true);
	echo "BXClearCache done\n";
}
if (class_exists(\Bitrix\Main\Application::class)) {
	try {
		\Bitrix\Main\Application::getInstance()->getManagedCache()->cleanAll();
		echo "managedCache cleanAll done\n";
	} catch (\Throwable $e) {
	}
}

// Prove
$check = $conn->query(
	"SELECT VALUE FROM b_user_option
	 WHERE USER_ID=0 AND CATEGORY='crm.entity.editor' AND NAME='lead_details_common'"
)->fetch();
$out = unserialize($check['VALUE']);
$names = [];
$walk = function ($nodes) use (&$walk, &$names) {
	foreach ($nodes as $n) {
		if (($n['type'] ?? '') === 'section' || ($n['type'] ?? '') === 'column') {
			$walk($n['elements'] ?? []);
		} elseif (isset($n['name'])) {
			$names[] = $n['name'];
		}
	}
};
$walk($out);
$need = [
	'UF_CRM_1731838126127',
	'UF_CRM_1756638760279',
	'UF_CRM_1770537051525',
	'UF_CRM_1763390140',
	'UF_CRM_1763390179',
	'UF_CRM_1736306439793',
	'PHONE',
	'UF_CRM_1760707563281',
];
foreach ($need as $f) {
	echo in_array($f, $names, true) ? "OK $f\n" : "MISSING $f\n";
}
echo "total_fields=", count($names), "\n";
echo "sections=";
foreach ($out[0]['elements'] ?? [] as $sec) {
	echo "[", $sec['title'] ?? '?', "] ";
}
echo "\nOK form updated\n";
