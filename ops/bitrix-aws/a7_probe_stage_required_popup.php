<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$root = $_SERVER['DOCUMENT_ROOT'];
echo "=== phrase ===\n";
passthru('grep -R -l -i "required fields to change" ' . escapeshellarg($root . '/bitrix/modules/crm/lang') . ' 2>/dev/null | head -20');
passthru('grep -R -n -i "REQUIRED_FIELD" ' . escapeshellarg($root . '/bitrix/modules/crm/lang/en') . ' 2>/dev/null | head -40');

echo "\n=== field labels ===\n";
$conn = \Bitrix\Main\Application::getConnection();
$names = [
	'UF_CRM_1731838813769','UF_CRM_1758002109','UF_CRM_1734162646510','UF_CRM_1731838049723',
	'UF_CRM_1731838581336','UF_CRM_1731838620873','UF_CRM_1731838640428','UF_CRM_1739869968682',
	'UF_CRM_1761633899','UF_CRM_1761633927','UF_CRM_1761633993','UF_CRM_1761633956',
];
$in = "'" . implode("','", $names) . "'";
$q = $conn->query(
	"SELECT f.FIELD_NAME, f.USER_TYPE_ID, l.EDIT_FORM_LABEL
	 FROM b_user_field f
	 LEFT JOIN b_user_field_lang l ON l.USER_FIELD_ID=f.ID AND l.LANGUAGE_ID='en'
	 WHERE f.ENTITY_ID='CRM_LEAD' AND f.FIELD_NAME IN ($in)"
);
while ($r = $q->fetch()) {
	echo $r['FIELD_NAME'], "\t", $r['USER_TYPE_ID'], "\t", $r['EDIT_FORM_LABEL'], "\n";
}

echo "\n=== form has them? ===\n";
$row = $conn->query(
	"SELECT VALUE FROM b_user_option WHERE USER_ID=0 AND CATEGORY='crm.entity.editor' AND NAME='lead_details_common'"
)->fetch();
$cfg = unserialize($row['VALUE']);
$have = [];
$walk = function ($nodes) use (&$walk, &$have) {
	foreach ($nodes as $n) {
		if (!is_array($n)) continue;
		if (isset($n['elements'])) $walk($n['elements']);
		if (isset($n['name']) && ($n['type'] ?? '') !== 'section' && ($n['type'] ?? '') !== 'column') {
			$have[$n['name']] = true;
		}
	}
};
$walk($cfg);
foreach ($names as $n) {
	echo (isset($have[$n]) ? 'ON  ' : 'OFF '), $n, "\n";
}
echo isset($have['OPPORTUNITY_WITH_CURRENCY']) ? "ON  OPPORTUNITY\n" : "OFF OPPORTUNITY\n";
