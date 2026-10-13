<?php
/**
 * Read-only: what Farhat Shahid (2299) sees as Work report "To".
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
CModule::IncludeModule('timeman');

const FARHAT = 2299;

$u = CUser::GetByID(FARHAT)->Fetch();
echo 'user=' . FARHAT . ' ' . trim(($u['NAME'] ?? '') . ' ' . ($u['LAST_NAME'] ?? '')) . ' dept=' . json_encode($u['UF_DEPARTMENT'] ?? null) . "\n";

$mgrs = CTimeMan::getUserManagers(FARHAT);
$ids = is_array($mgrs) ? array_values($mgrs) : [];
$first = $ids ? (int)$ids[0] : 0;
echo 'getUserManagers=' . json_encode($ids) . "\n";

$names = [];
foreach ($ids as $id) {
	$row = CUser::GetByID((int)$id)->Fetch();
	$names[(int)$id] = $row
		? trim(($row['NAME'] ?? '') . ' ' . ($row['LAST_NAME'] ?? ''))
		: '?';
}
echo 'manager_names=' . json_encode($names) . "\n";
echo 'work_report_To=' . ($first ? ($names[$first] . ' (' . $first . ')') : '(none)') . "\n";

$c = \Bitrix\Main\Application::getConnection();
$rs = $c->query(
	"SELECT m.ID, m.NODE_ID, m.ACTIVE, n.NAME, GROUP_CONCAT(r.NAME) AS ROLES
	 FROM b_hr_structure_node_member m
	 JOIN b_hr_structure_node n ON n.ID=m.NODE_ID
	 LEFT JOIN b_hr_structure_node_member_role mr ON mr.MEMBER_ID=m.ID
	 LEFT JOIN b_hr_structure_role r ON r.ID=mr.ROLE_ID
	 WHERE m.ENTITY_TYPE='USER' AND m.ENTITY_ID=" . FARHAT . "
	 GROUP BY m.ID, m.NODE_ID, m.ACTIVE, n.NAME"
);
echo "hr_membership:\n";
while ($row = $rs->fetch()) {
	echo '  node=' . $row['NODE_ID'] . ' active=' . $row['ACTIVE']
		. ' name=' . $row['NAME'] . ' roles=' . ($row['ROLES'] ?? '') . "\n";
}
