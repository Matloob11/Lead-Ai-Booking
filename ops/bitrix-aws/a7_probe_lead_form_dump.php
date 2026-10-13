<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$conn = \Bitrix\Main\Application::getConnection();
$res = $conn->query(
	"SELECT ID, NAME, COMMON, AUTO_APPLY_SCOPE, CONFIG
	 FROM b_ui_entity_editor_config
	 WHERE ENTITY_TYPE_ID='lead_details'
	 ORDER BY ID"
);

function walk($nodes, $indent = 0): void
{
	if (!is_array($nodes)) {
		return;
	}
	foreach ($nodes as $node) {
		if (!is_array($node)) {
			continue;
		}
		$type = $node['type'] ?? '';
		$name = $node['name'] ?? '';
		$title = $node['title'] ?? '';
		$pad = str_repeat('  ', $indent);
		if ($type === 'column' || $type === 'section') {
			echo $pad, strtoupper($type), " [$name] title=", $title, "\n";
			walk($node['elements'] ?? [], $indent + 1);
		} else {
			echo $pad, "FIELD ", $name, ($title !== '' ? " ($title)" : ''), "\n";
		}
	}
}

while ($row = $res->fetch()) {
	echo "\n######## ID=", $row['ID'], " NAME=", $row['NAME'], " COMMON=", $row['COMMON'], " AUTO=", $row['AUTO_APPLY_SCOPE'], " ########\n";
	$cfg = @unserialize($row['CONFIG']);
	if ($cfg === false) {
		$cfg = json_decode($row['CONFIG'], true);
	}
	if (!is_array($cfg)) {
		echo "parse fail\n";
		continue;
	}
	walk($cfg);
}

// Also user personal options that override
$opts = $conn->query(
	"SELECT USER_ID, NAME, LEFT(VALUE, 200) AS v, LENGTH(VALUE) AS len
	 FROM b_user_option
	 WHERE CATEGORY='crm.entity.editor' AND NAME LIKE '%lead%'
	 ORDER BY USER_ID DESC LIMIT 15"
);
echo "\n=== user options (sample) ===\n";
while ($o = $opts->fetch()) {
	echo json_encode($o, JSON_UNESCAPED_UNICODE), "\n";
}

// Lead 79318 field values for the ones on the card
$u = $conn->query(
	"SELECT u.UF_CRM_1731838126127 beds, u.UF_CRM_1756638760279 client_type,
	        u.UF_CRM_1770537051525 community_text, u.UF_CRM_1763390140 community_link,
	        u.UF_CRM_1763390179 sub_community, u.UF_CRM_1760707563281 pref,
	        u.UF_CRM_1760707872553 portal_id, u.UF_CRM_1736306439793 deal_amt,
	        u.UF_CRM_1760707550978 prop_link
	 FROM b_uts_crm_lead u WHERE u.VALUE_ID=79318"
)->fetch();
echo "\n=== lead 79318 values ===\n";
print_r($u);
