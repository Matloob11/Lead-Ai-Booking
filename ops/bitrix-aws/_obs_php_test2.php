#!/usr/bin/env php
<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['HTTP_HOST'] = 'crm.a7grouprealestatedxb.com';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);
require $_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php';

function assert_true($c, $m) { echo ($c ? 'OK ' : 'FAIL ').$m."\n"; if (!$c) { fwrite(STDERR, "failed: $m\n"); } }

$json = '["user","all-agents"]';
assert_true(A7ObserverFilter::payloadHasToken($json), 'token in json pair string');
assert_true(A7ObserverFilter::payloadHasToken(['OBSERVER_IDS' => [$json]]), 'token in filter fields');
assert_true(!A7ObserverFilter::payloadHasToken(['OBSERVER_IDS' => ['["user","21"]']]), 'real user is not token');

$f = ['OBSERVER_IDS' => [$json], 'STATUS_SEMANTIC_ID' => 'P'];
A7ObserverFilter::applyToCrmFilter($f);
$ids = $f['OBSERVER_IDS'] ?? [];
assert_true(is_array($ids) && count($ids) >= 60, 'expanded count='.count((array)$ids));
assert_true(!A7ObserverFilter::payloadHasToken($ids), 'token gone after apply');
assert_true(in_array(21, array_map('intval', $ids), true), 'has user 21');

$f2 = ['OBSERVER_IDS' => [0]];
// without saved options this should not blindly expand if shouldExpand needs token - [0] only expands with saved options
echo 'zero_only_keys='.json_encode(array_keys($f2))."\n";

$sql = CCrmEntityHelper::prepareObserversFieldFilter(1, 'L', $ids);
assert_true(strpos($sql, 'b_crm_observer') !== false && strpos($sql, 'IN (') !== false, 'sql built');

$cnt = Bitrix\Main\Application::getConnection()->queryScalar(
    'SELECT COUNT(*) FROM b_crm_lead L WHERE '.$sql
);
echo "observer_lead_count=$cnt\n";
assert_true((int)$cnt > 100 && (int)$cnt < 5000, 'count is observer subset not all leads');

$all = Bitrix\Main\Application::getConnection()->queryScalar('SELECT COUNT(*) FROM b_crm_lead');
echo "all_leads=$all\n";
assert_true((int)$cnt < (int)$all, 'subset of all');

echo class_exists('A7KanbanLead', false) ? "kanban_class_before_hook=Y\n" : "kanban_class_before_hook=N\n";
A7ObserverFilter::installKanbanHook();
echo class_exists('A7KanbanLead', false) ? "kanban_class_after_hook=Y\n" : "kanban_class_after_hook=N\n";
$svc = Bitrix\Main\DI\ServiceLocator::getInstance()->get('crm.kanban.entity.lead');
echo 'service='.get_class($svc)."\n";
assert_true($svc instanceof A7KanbanLead, 'locator returns A7KanbanLead');

echo 'DONE';
