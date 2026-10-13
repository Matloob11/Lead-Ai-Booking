<?php
/**
 * Prove boot payload + asset paths for lead 79317 without a browser session.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$_SERVER['REQUEST_URI'] = '/crm/lead/details/79317/';
$boot = A7PortalLeadFields::bootPayload();
echo json_encode([
	'leadId' => $boot['leadId'],
	'isPortal' => $boot['isPortal'],
	'sourceId' => $boot['sourceId'] ?? '',
	'hideCount' => count($boot['hideFields'] ?? []),
	'alwaysOther' => $boot['alwaysOther'] ?? [],
	'otherTitle' => $boot['otherTitle'] ?? '',
	'lockCreate' => $boot['lockCreate'] ?? false,
], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), "\n";

// Non-portal control: find a recent non-portal lead
$conn = \Bitrix\Main\Application::getConnection();
$row = $conn->query(
	"SELECT ID, SOURCE_ID FROM b_crm_lead
	 WHERE SOURCE_ID NOT IN ('UC_KQ0WO3','UC_Y3VNS9','UC_BUIJB2','UC_D83356','UC_4FVN3G','UC_PCVWT4','UC_6R3AM9','UC_LX9888','UC_JPSVQU')
	   AND SOURCE_ID IS NOT NULL AND SOURCE_ID <> ''
	 ORDER BY ID DESC LIMIT 1"
)->fetch();
if ($row) {
	$_SERVER['REQUEST_URI'] = '/crm/lead/details/' . (int)$row['ID'] . '/';
	$b2 = A7PortalLeadFields::bootPayload();
	echo 'non_portal_lead=', $row['ID'], ' source=', $row['SOURCE_ID'], ' isPortal=', ($b2['isPortal'] ? 'yes' : 'no'), "\n";
}
echo "OK\n";
