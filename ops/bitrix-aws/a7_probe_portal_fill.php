<?php
/**
 * Fill rates for portal-source leads (last 30 days) — read-only.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$sources = [
	'UC_KQ0WO3','UC_D83356','UC_6R3AM9', // PF
	'UC_Y3VNS9','UC_4FVN3G','UC_PCVWT4', // Bayut
	'UC_BUIJB2','UC_LX9888','UC_JPSVQU', // Dubizzle
];
$in = "'" . implode("','", $sources) . "'";

$fields = [
	'UF_CRM_1760707563281' => 'Property Reference',
	'UF_CRM_1760707872553' => 'Portal Lead ID',
	'UF_CRM_1760707550978' => 'Property Link',
	'UF_CRM_1770537051525' => 'Community',
	'UF_CRM_1763390140' => 'Community (old)',
	'UF_CRM_1731838126127' => 'No. of Bedrooms',
	'UF_CRM_1736306439793' => 'Deal Amount',
	'UF_CRM_1760707526983' => 'Permit/DTMC',
	'UF_CRM_1740043316741' => 'Budget Range',
	'UF_CRM_1765536351834' => 'Call Recording',
	'UF_CRM_1736316526892' => 'Mobile Number',
	'UF_CRM_1733420484604' => 'Secondary Phone Number',
	'UF_CRM_1734247755389' => 'Phone (Owner Data)',
	'UF_CRM_1786771496574' => '971529647138',
	'UF_CRM_1786771731997' => 'New number',
	'UF_CRM_A7_AI_COMMUNITY_FLEXIBILITY' => 'Community Flexibility',
	'UF_CRM_1760707431859' => 'Property Title',
	'UF_CRM_1760707444' => 'Property Description',
	'UF_CRM_1760707482053' => 'Property Size',
	'UF_CRM_1735126982325' => 'Offering Type',
	'UF_CRM_1756638760279' => 'owner (Client Type)',
	'UF_CRM_1769936696380' => 'Lead Type',
	'UF_CRM_1770537849303' => 'Sub Source',
	'UF_CRM_A7_RENT_SALE' => 'Rent / Sale',
	'UF_CRM_1760707543984' => 'WhatsApp Tracking Link',
	'UF_CRM_1731838049723' => 'Project Name (string)',
	'UF_CRM_1733420840732' => 'Preffered Area',
	'COMMENTS' => 'Comments',
];

$conn = \Bitrix\Main\Application::getConnection();
$total = (int)$conn->queryScalar(
	"SELECT COUNT(*) FROM b_crm_lead l
	 WHERE l.SOURCE_ID IN ($in)
	   AND l.DATE_CREATE >= DATE_SUB(NOW(), INTERVAL 30 DAY)
	   AND 1=1"
);
echo "total_portal_30d=$total\n";

foreach ($fields as $col => $label) {
	if ($col === 'COMMENTS') {
		$filled = (int)$conn->queryScalar(
			"SELECT COUNT(*) FROM b_crm_lead l
			 WHERE l.SOURCE_ID IN ($in)
			   AND l.DATE_CREATE >= DATE_SUB(NOW(), INTERVAL 30 DAY)
			   AND 1=1
			   AND l.COMMENTS IS NOT NULL AND TRIM(l.COMMENTS)<>''"
		);
	} else {
		$filled = (int)$conn->queryScalar(
			"SELECT COUNT(*) FROM b_crm_lead l
			 JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
			 WHERE l.SOURCE_ID IN ($in)
			   AND l.DATE_CREATE >= DATE_SUB(NOW(), INTERVAL 30 DAY)
			   AND 1=1
			   AND u.`$col` IS NOT NULL AND TRIM(CAST(u.`$col` AS CHAR))<>'' AND TRIM(CAST(u.`$col` AS CHAR))<>'0'"
		);
	}
	$pct = $total > 0 ? round(100 * $filled / $total, 1) : 0;
	echo sprintf("%5d  %5.1f%%  %-40s %s\n", $filled, $pct, $col, $label);
}

// Phone multifield
$phoneFilled = (int)$conn->queryScalar(
	"SELECT COUNT(DISTINCT l.ID) FROM b_crm_lead l
	 JOIN b_crm_field_multi m ON m.ENTITY_ID='LEAD' AND m.ELEMENT_ID=l.ID AND m.TYPE_ID='PHONE'
	 WHERE l.SOURCE_ID IN ($in)
	   AND l.DATE_CREATE >= DATE_SUB(NOW(), INTERVAL 30 DAY)
	   AND 1=1
	   AND m.VALUE IS NOT NULL AND TRIM(m.VALUE)<>''"
);
$pct = $total > 0 ? round(100 * $phoneFilled / $total, 1) : 0;
echo sprintf("%5d  %5.1f%%  %-40s %s\n", $phoneFilled, $pct, 'FM:PHONE', 'Phone (system)');
