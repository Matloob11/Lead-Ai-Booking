<?php
/**
 * Delete orphan C32 proof lead 79630 left after a failed first run.
 * CLI only.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

\Bitrix\Main\Loader::includeModule('crm');
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$conn = \Bitrix\Main\Application::getConnection();

foreach ([79630] as $leadId) {
    $acts = $conn->query(
        "SELECT a.ID FROM b_crm_act a
         INNER JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
         WHERE b.OWNER_TYPE_ID=" . \CCrmOwnerType::Lead . " AND b.OWNER_ID=" . (int)$leadId
    );
    while ($row = $acts->fetch()) {
        $tid = (int)$row['ID'];
        $conn->queryExecute('DELETE FROM b_crm_act_bind WHERE ACTIVITY_ID=' . $tid);
        $conn->queryExecute('DELETE FROM b_crm_act WHERE ID=' . $tid);
        echo "ACT $tid\n";
    }
    $item = $factory->getItem($leadId);
    if ($item) {
        $del = $factory->getDeleteOperation($item, $context);
        $del->disableCheckAccess();
        $del->disableBizProc();
        $del->disableAutomation();
        $del->launch();
    }
    echo 'LEAD ' . $leadId . ' ' . ($factory->getItem($leadId) === null ? 'gone' : 'still') . "\n";
}
echo "DONE\n";
