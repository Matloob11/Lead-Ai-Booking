<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_CRONTAB', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
$ids = [77578, 77566, 77564, 77496, 77495, 77494, 77416];
$crm = new CCrmLead(false);
$ok = 0;
foreach ($ids as $id) {
    $deleted = $crm->Delete($id, [
        'ENABLE_SYSTEM_EVENTS' => false,
        'PROCESS_BIZPROC' => false,
        'REGISTER_SONET_EVENT' => false,
    ]);
    echo $id, ' ', ($deleted ? 'ok' : ('fail ' . $crm->LAST_ERROR)), "\n";
    if ($deleted) $ok++;
}
echo "DELETED $ok\n";
