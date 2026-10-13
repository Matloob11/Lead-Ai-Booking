#!/usr/bin/env php
<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['HTTP_HOST'] = 'crm.a7grouprealestatedxb.com';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);
require $_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

echo 'builder_file='.(new ReflectionClass('CCrmEntityListBuilder'))->getFileName()."\n";

function count_leads($filter) {
    $filter['CHECK_PERMISSIONS'] = 'N';
    $n = 0;
    $res = CCrmLead::GetListEx(['ID' => 'DESC'], $filter, false, ['nTopCount' => 5000], ['ID']);
    while ($res && $res->Fetch()) { $n++; }
    return $n;
}

$nToken = count_leads(['OBSERVER_IDS' => ['["user","all-agents"]']]);
$nZero = count_leads(['OBSERVER_IDS' => [0]]);
$nUser = count_leads(['OBSERVER_IDS' => [21]]);
$nPlain = count_leads([]);
echo "count_token=$nToken count_zero=$nZero count_user21=$nUser count_plain=$nPlain\n";

$ent = \Bitrix\Crm\Kanban\Entity::getInstance('LEAD');
echo 'getInstance='.get_class($ent)."\n";

echo ($nToken > 100 && $nToken < 5000 && $nToken < $nPlain) ? "PASS_TOKEN\n" : "FAIL_TOKEN\n";
echo ($nZero > 100 && $nZero < 5000 && $nZero < $nPlain) ? "PASS_ZERO\n" : "FAIL_ZERO\n";
echo ($nUser > 0 && $nUser <= $nToken) ? "PASS_USER\n" : "FAIL_USER\n";
