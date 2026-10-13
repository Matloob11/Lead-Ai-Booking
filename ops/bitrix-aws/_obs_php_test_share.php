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
if (is_object($USER) && method_exists($USER, 'Authorize')) {
    $USER->Authorize(2311);
}

$c = \Bitrix\Main\Application::getConnection();
$tbl = $c->isTableExists('a7_lead_share') ? 'Y' : 'N';
$shareLeads = $tbl === 'Y' ? (int)$c->queryScalar('SELECT COUNT(DISTINCT LEAD_ID) FROM a7_lead_share') : 0;
$shareRows = $tbl === 'Y' ? (int)$c->queryScalar('SELECT COUNT(*) FROM a7_lead_share') : 0;
echo "table=$tbl share_leads=$shareLeads share_rows=$shareRows\n";

echo 'payload_shared='.(A7ObserverFilter::payloadHasShared(['OBSERVER_IDS'=>['["user","shared-leads"]']]) ? 'Y':'N')."\n";
echo 'payload_not_all='.(A7ObserverFilter::payloadHasToken(['OBSERVER_IDS'=>['["user","shared-leads"]']]) ? 'Y':'N')."\n";

$ids = A7ObserverFilter::sharedLeadIds();
echo 'sharedLeadIds='.count($ids)."\n";

$f = ['OBSERVER_IDS' => ['["user","shared-leads"]'], 'CHECK_PERMISSIONS' => 'N'];
A7ObserverFilter::applyToCrmFilter($f);
echo 'has_shared_ids='.(isset($f['__A7_SHARED_IDS']) && is_array($f['__A7_SHARED_IDS']) ? count($f['__A7_SHARED_IDS']) : 0)."\n";
echo 'obs_unset='.(isset($f['OBSERVER_IDS']) ? 'N':'Y')."\n";

$n = 0;
$res = CCrmLead::GetListEx(['ID'=>'DESC'], ['CHECK_PERMISSIONS'=>'N','OBSERVER_IDS'=>['["user","shared-leads"]']], false, ['nTopCount'=>5000], ['ID']);
while ($res && $res->Fetch()) { $n++; }
echo "count_shared_filter=$n\n";
echo ($shareLeads > 0 && $n === min($shareLeads, 5000)) ? "PASS\n" : (($shareLeads===0 && $n===0)?"PASS_EMPTY\n":"FAIL\n");
