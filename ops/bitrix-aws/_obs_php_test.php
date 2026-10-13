#!/usr/bin/env php
<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
$_SERVER['HTTP_HOST'] = 'crm.a7grouprealestatedxb.com';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);
require $_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php';

$_POST = [
    'FIELDS' => [
        'OBSERVER_IDS' => ['all-agents', 'user_21'],
    ],
    'FILTER' => json_encode(['OBSERVER_IDS' => ['all-agents']]),
];
$_REQUEST = $_POST;
A7ObserverFilter::rewriteSuperglobals();
$ids = $_POST['FIELDS']['OBSERVER_IDS'];
echo 'expanded_count='.(is_array($ids)?count($ids):0)."\n";
echo 'has_21='.(in_array(21, array_map('intval', (array)$ids), true) ? 'Y' : 'N')."\n";
echo 'token_gone='.(in_array('all-agents', (array)$ids, true) ? 'N' : 'Y')."\n";
$decoded = json_decode($_POST['FILTER'], true);
$j = $decoded['OBSERVER_IDS'] ?? [];
echo 'json_count='.(is_array($j)?count($j):0)."\n";
echo 'json_sample='.implode(',', array_slice((array)$j, 0, 5))."\n";
echo 'js_ok='.(is_readable('/home/bitrix/www/bitrix/js/a7_observer_filter.js')?'Y':'N')."\n";
echo 'OK';
