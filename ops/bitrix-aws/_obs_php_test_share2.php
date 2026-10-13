#!/usr/bin/env php
<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['HTTP_HOST'] = 'crm.a7grouprealestatedxb.com';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);
require $_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
global $USER;
$USER->Authorize(2311);

$opt = \CUserOptions::GetOption('main.ui.filter', 'CRM_LEAD_LIST_V12', false);
$fields = $opt['tmp_filter']['fields'] ?? [];
echo 'tmp_obs='.json_encode($fields['OBSERVER_IDS'] ?? null)."\n";
echo 'tmp_label='.json_encode($fields['OBSERVER_IDS_label'] ?? null)."\n";
echo 'has_shared_token='.(A7ObserverFilter::payloadHasShared($fields)?'Y':'N')."\n";
echo 'has_all_token='.(A7ObserverFilter::payloadHasToken($fields)?'Y':'N')."\n";

function count_by($filter) {
    $filter['CHECK_PERMISSIONS'] = 'N';
    $n=0; $by=[];
    $res = CCrmLead::GetListEx([], $filter, false, ['nTopCount'=>5000], ['ID','STATUS_ID']);
    while ($r = $res->Fetch()) {
        $n++;
        $s=$r['STATUS_ID']??'';
        $by[$s]=($by[$s]??0)+1;
    }
    return [$n, $by];
}

[$n0,$b0]=count_by(['OBSERVER_IDS'=>[0]]);
echo "zeroish_total=$n0 inp=".($b0['IN_PROCESS']??0)." assigned=".($b0['UC_MJDO60']??0)." ai=".($b0['12']??0)."\n";

[$nJ,$bJ]=count_by(['OBSERVER_IDS'=>['["user","shared-leads"]']]);
echo "json_total=$nJ inp=".($bJ['IN_PROCESS']??0)." assigned=".($bJ['UC_MJDO60']??0)." ai=".($bJ['12']??0)."\n";

$f=['OBSERVER_IDS'=>[0]];
A7ObserverFilter::applyToCrmFilter($f);
echo 'after_apply keys='.implode(',', array_keys($f))."\n";
echo 'shared_ids='.(isset($f['__A7_SHARED_IDS'])?count($f['__A7_SHARED_IDS']):0)."\n";
echo 'obs='.(isset($f['OBSERVER_IDS'])?'Y':'N')."\n";
