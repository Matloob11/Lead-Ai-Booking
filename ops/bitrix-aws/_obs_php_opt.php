#!/usr/bin/env php
<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['HTTP_HOST'] = 'crm.a7grouprealestatedxb.com';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php';
global $USER;
$USER->Authorize(2311);
$opt = \CUserOptions::GetOption('main.ui.filter', 'CRM_LEAD_LIST_V12', false);
echo 'keys='.implode(',', array_keys((array)$opt))."\n";
echo 'filter='.json_encode($opt['filter'] ?? null)."\n";
echo 'default='.json_encode($opt['default'] ?? null)."\n";
echo 'tmp_keys='.implode(',', array_keys((array)($opt['tmp_filter'] ?? [])))."\n";
$tf=$opt['tmp_filter']['fields'] ?? null;
echo 'tmp_fields_is_array='.(is_array($tf)?'Y':'N').' count='.(is_array($tf)?count($tf):0)."\n";
if (is_array($tf)) echo 'tmp_field_names='.implode(',', array_keys($tf))."\n";
$blob=serialize($opt);
echo 'ser_shared='.(strpos($blob,'shared-leads')!==false?'Y':'N')."\n";
echo 'ser_all='.(strpos($blob,'all-agents')!==false?'Y':'N')."\n";
if (isset($opt['filters']) && is_array($opt['filters'])) {
  foreach ($opt['filters'] as $id=>$f) {
    $s=serialize($f);
    if (strpos($s,'shared-leads')!==false || strpos($s,'OBSERVER')!==false) {
      echo "preset $id obs=".json_encode($f['fields']['OBSERVER_IDS']??null)." label=".json_encode($f['fields']['OBSERVER_IDS_label']??null)."\n";
    }
  }
}
