<?php
/**
 * Prove a new lead stage cannot be created without the admin password,
 * then move Invalid number + Agent leads to Assigned and delete those stages.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_CRONTAB', true);
define('A7_STAGE_ADMIN_FORCE_WEB', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

\Bitrix\Main\Loader::includeModule('crm');

$probe = \Bitrix\Crm\StatusTable::add([
    'ENTITY_ID' => 'STATUS',
    'STATUS_ID' => 'A7LOCKPROBE',
    'NAME' => 'A7 lock probe',
    'SORT' => 9998,
    'SYSTEM' => 'N',
    'SEMANTICS' => 'P',
]);
if ($probe->isSuccess()) {
    \Bitrix\Crm\StatusTable::delete($probe->getId());
    fwrite(STDERR, "LOCK_FAIL stage was created without a password\n");
    exit(1);
}
echo 'LOCK_OK ' . implode(' ', $probe->getErrorMessages()) . "\n";

$from = ['UC_EZQBQD', 'UC_XOKU71'];
$to = 'UC_MJDO60';
$lead = new CCrmLead(false);
$moved = 0;
$failed = 0;
$rs = CCrmLead::GetListEx(
    ['ID' => 'ASC'],
    ['STATUS_ID' => $from, 'CHECK_PERMISSIONS' => 'N'],
    false,
    false,
    ['ID', 'STATUS_ID']
);
while ($row = $rs->Fetch()) {
    $fields = ['STATUS_ID' => $to];
    $ok = $lead->Update(
        (int)$row['ID'],
        $fields,
        true,
        true,
        [
            'ENABLE_SYSTEM_EVENTS' => false,
            'DISABLE_USER_FIELD_CHECK' => true,
            'REGISTER_SONET_EVENT' => false,
        ]
    );
    if ($ok) {
        $moved++;
    } else {
        $failed++;
        fwrite(STDERR, 'MOVE_FAIL ' . $row['ID'] . ' ' . $lead->LAST_ERROR . "\n");
    }
}
echo "MOVED $moved FAILED $failed\n";

$status = new CCrmStatus('STATUS');
foreach ([705, 709] as $id) {
    $ok = $status->Delete($id);
    echo 'DELETE ' . $id . ' ' . ($ok ? 'ok' : ('fail ' . $status->GetLastError())) . "\n";
}

$left = 0;
$rs = CCrmLead::GetListEx(
    [],
    ['STATUS_ID' => $from, 'CHECK_PERMISSIONS' => 'N'],
    false,
    false,
    ['ID']
);
while ($rs->Fetch()) {
    $left++;
}
echo "LEFT $left\n";
