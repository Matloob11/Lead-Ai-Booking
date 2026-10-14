<?php
/** Count the C15 preset the way the list filter does, and the same conditions in SQL. CLI only. */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$filter = [
    'CHECK_PERMISSIONS' => 'N',
    '=UF_CRM_1770537051525' => 'International City',
    '=UF_CRM_1731838348693' => 384,
    'HAS_PHONE' => 'Y',
    [
        'LOGIC' => 'OR',
        ['UF_CRM_A7_BOT_STATUS' => false],
        ['=UF_CRM_A7_BOT_STATUS' => 2475],
        ['=UF_CRM_A7_BOT_STATUS' => 2476],
    ],
    [
        'LOGIC' => 'OR',
        ['UF_CRM_A7_WA_OPT_OUT' => false],
        ['=UF_CRM_A7_WA_OPT_OUT' => 2483],
    ],
];
$crm = 0;
$res = \CCrmLead::GetListEx([], $filter, false, false, ['ID']);
while ($res && $res->Fetch()) {
    $crm++;
}
$sql = (int)\Bitrix\Main\Application::getConnection()->queryScalar(
    "SELECT COUNT(DISTINCT l.ID) FROM b_crm_lead l
     JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
     JOIN b_crm_field_multi fm ON fm.ENTITY_ID='LEAD' AND fm.ELEMENT_ID=l.ID
       AND fm.TYPE_ID='PHONE' AND fm.VALUE<>''
     WHERE u.UF_CRM_1770537051525='International City'
       AND u.UF_CRM_1731838348693=384
       AND (u.UF_CRM_A7_BOT_STATUS IS NULL OR u.UF_CRM_A7_BOT_STATUS=0
            OR u.UF_CRM_A7_BOT_STATUS IN (2475,2476))
       AND (u.UF_CRM_A7_WA_OPT_OUT IS NULL OR u.UF_CRM_A7_WA_OPT_OUT=0
            OR u.UF_CRM_A7_WA_OPT_OUT<>2482)"
);
$saved = \CUserOptions::GetOption('main.ui.filter.common', 'CRM_LEAD_LIST_V12', [], 0);
$name = is_array($saved) ? ($saved['filters']['a7_ic_shops_ready']['name'] ?? '') : '';
echo 'preset=', $name, "\n";
echo 'crm=', $crm, ' sql=', $sql, ' match=', $crm === $sql ? 'yes' : 'no', "\n";
