<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$conn = \Bitrix\Main\Application::getConnection();
$row = $conn->query(
	"SELECT ID, USER_ID, CATEGORY, NAME, VALUE
	 FROM b_user_option
	 WHERE USER_ID=0 AND CATEGORY='crm.entity.editor' AND NAME='lead_details_common'
	 LIMIT 1"
)->fetch();
if (!$row) {
	fwrite(STDERR, "no common form\n");
	exit(1);
}
echo "option_id=", $row['ID'], " len=", strlen($row['VALUE']), "\n";
$cfg = unserialize($row['VALUE']);

function walk($nodes, $indent = 0): void
{
	foreach ($nodes as $node) {
		if (!is_array($node)) {
			continue;
		}
		$type = $node['type'] ?? '';
		$name = $node['name'] ?? '';
		$title = $node['title'] ?? '';
		$pad = str_repeat('  ', $indent);
		if ($type === 'column' || $type === 'section') {
			echo $pad, strtoupper($type), " [$name] title=", json_encode($title), "\n";
			walk($node['elements'] ?? [], $indent + 1);
		} else {
			echo $pad, "FIELD ", $name, "\n";
		}
	}
}
walk($cfg);

// How many personal overrides exist
$n = (int)$conn->queryScalar(
	"SELECT COUNT(*) FROM b_user_option
	 WHERE CATEGORY='crm.entity.editor' AND NAME='lead_details' AND USER_ID>0"
);
echo "personal_lead_details_overrides=$n\n";
