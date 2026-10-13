<?php
// Creates the Rent / Sale dropdown field on leads (idempotent), its three
// values, and backfills existing leads from Client Type + Offering Type.
// Direct SQL for the backfill so no lead automations fire.
// Run: sudo -u bitrix php -d display_errors=1 deploy_rent_sale_setup.php [--apply]
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
global $DB, $APPLICATION;
$APPLY = in_array('--apply', $argv, true);
$FIELD = 'UF_CRM_A7_RENT_SALE';
$langs = ['en', 'br', 'fr', 'it', 'la', 'pl', 'ua'];
$mk = function ($v) use ($langs) { $a = []; foreach ($langs as $l) { $a[$l] = $v; } return $a; };
function scalar($sql) { global $DB; $r = $DB->Query($sql)->Fetch(); return $r ? array_values($r)[0] : null; }

echo "mode=" . ($APPLY ? 'APPLY' : 'DRY-RUN') . "\n";

// 1) field
$fid = (int)scalar("SELECT ID FROM b_user_field WHERE ENTITY_ID='CRM_LEAD' AND FIELD_NAME='$FIELD'");
if ($fid > 0) {
    echo "field exists id=$fid\n";
} elseif (!$APPLY) {
    echo "would CREATE field $FIELD (enumeration)\n";
} else {
    $e = new CUserTypeEntity;
    $fid = (int)$e->Add([
        'ENTITY_ID' => 'CRM_LEAD', 'FIELD_NAME' => $FIELD, 'USER_TYPE_ID' => 'enumeration',
        'XML_ID' => 'A7_RENT_SALE', 'SORT' => 100, 'MULTIPLE' => 'N', 'MANDATORY' => 'N',
        'SHOW_FILTER' => 'I', 'SHOW_IN_LIST' => 'Y', 'EDIT_IN_LIST' => 'Y', 'IS_SEARCHABLE' => 'N',
        'SETTINGS' => ['DISPLAY' => 'LIST', 'LIST_HEIGHT' => 1, 'CAPTION_NO_VALUE' => '', 'SHOW_NO_VALUE' => 'Y'],
        'EDIT_FORM_LABEL' => $mk('Rent / Sale'), 'LIST_COLUMN_LABEL' => $mk('Rent / Sale'),
        'LIST_FILTER_LABEL' => $mk('Rent / Sale'), 'ERROR_MESSAGE' => $mk(''), 'HELP_MESSAGE' => $mk(''),
    ]);
    if ($fid <= 0) {
        $ex = $APPLICATION->GetException();
        echo "CREATE FAILED: " . ($ex ? $ex->GetString() : '?') . "\n";
        exit(1);
    }
    echo "field created id=$fid\n";
}

// 2) enum values
$want = ['Rent' => 100, 'Sale' => 200, 'Rent & Sale' => 300];
$have = [];
if ($fid > 0) {
    $r = $DB->Query("SELECT ID, VALUE FROM b_user_field_enum WHERE USER_FIELD_ID=$fid");
    while ($x = $r->Fetch()) { $have[trim($x['VALUE'])] = (int)$x['ID']; }
}
$missing = array_diff_key($want, $have);
if ($missing) {
    if (!$APPLY) {
        echo "would ADD values: " . implode(', ', array_keys($missing)) . "\n";
    } else {
        $en = new CUserFieldEnum;
        $arr = []; $i = 0;
        foreach ($have as $v => $id) { $arr[$id] = ['ID' => $id, 'VALUE' => $v, 'SORT' => $want[$v] ?? 500, 'DEF' => 'N']; }
        foreach ($missing as $v => $sort) { $arr['n' . ($i++)] = ['VALUE' => $v, 'SORT' => $sort, 'DEF' => 'N']; }
        if (!$en->SetEnumValues($fid, $arr)) { echo "SetEnumValues FAILED\n"; exit(1); }
        $have = [];
        $r = $DB->Query("SELECT ID, VALUE FROM b_user_field_enum WHERE USER_FIELD_ID=$fid");
        while ($x = $r->Fetch()) { $have[trim($x['VALUE'])] = (int)$x['ID']; }
        echo "values set\n";
    }
}
foreach ($have as $v => $id) { echo "  enum '$v' = $id\n"; }

// 3) backfill
if ($fid <= 0 || count($have) < 3) { echo ($APPLY ? "nothing to backfill yet\n" : "backfill runs after create\n"); exit(0); }
$rentId = $have['Rent']; $saleId = $have['Sale']; $bothId = $have['Rent & Sale'];
$tenant = (int)scalar("SELECT e.ID FROM b_user_field_enum e JOIN b_user_field f ON f.ID=e.USER_FIELD_ID WHERE f.FIELD_NAME='UF_CRM_1756638760279' AND LOWER(e.VALUE)='tenant'");
$buyer  = (int)scalar("SELECT e.ID FROM b_user_field_enum e JOIN b_user_field f ON f.ID=e.USER_FIELD_ID WHERE f.FIELD_NAME='UF_CRM_1756638760279' AND LOWER(e.VALUE)='buyer'");
$seller = (int)scalar("SELECT e.ID FROM b_user_field_enum e JOIN b_user_field f ON f.ID=e.USER_FIELD_ID WHERE f.FIELD_NAME='UF_CRM_1756638760279' AND LOWER(e.VALUE)='seller'");
echo "sources: tenant=$tenant buyer=$buyer seller=$seller\n";
$rentSig = "(u.UF_CRM_1756638760279 = $tenant OR LOWER(TRIM(u.UF_CRM_1735126982325)) = 'rent')";
$saleSig = "(u.UF_CRM_1756638760279 IN ($buyer,$seller) OR LOWER(TRIM(u.UF_CRM_1735126982325)) = 'sale')";
$case = "CASE WHEN $rentSig AND $saleSig THEN $bothId WHEN $rentSig THEN $rentId WHEN $saleSig THEN $saleId END";
$empty = "(u.`$FIELD` IS NULL OR u.`$FIELD` = 0)";
$n = (int)scalar("SELECT COUNT(*) FROM b_uts_crm_lead u WHERE $empty AND ($case) IS NOT NULL");
echo "backfill candidates (field empty + has a signal): $n\n";
if ($APPLY && $n > 0) {
    $DB->Query("UPDATE b_uts_crm_lead u SET u.`$FIELD` = ($case) WHERE $empty AND ($case) IS NOT NULL");
    echo "backfilled\n";
}
echo "-- distribution --\n";
$r = $DB->Query("SELECT COALESCE(e.VALUE,'(empty)') v, COUNT(*) n FROM b_uts_crm_lead u LEFT JOIN b_user_field_enum e ON e.ID=u.`$FIELD` GROUP BY e.VALUE ORDER BY n DESC");
while ($x = $r->Fetch()) { echo "  " . $x['v'] . " = " . $x['n'] . "\n"; }
echo "DONE\n";
