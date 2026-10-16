<?php
/**
 * C42: find which CRM entity stores a7group-NNNN listings. Read-only. CLI only.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

function say(string $l): void
{
    echo $l, "\n";
}
$conn = \Bitrix\Main\Application::getConnection();

function qall($conn, string $sql): array
{
    $rows = [];
    $res = $conn->query($sql);
    while ($res && ($row = $res->fetch())) {
        $rows[] = $row;
    }
    return $rows;
}

say('== DYNAMIC TYPES ==');
foreach (qall($conn, 'SELECT ID, ENTITY_TYPE_ID, TITLE FROM b_crm_dynamic_type ORDER BY ENTITY_TYPE_ID') as $row) {
    say('DT ' . $row['ENTITY_TYPE_ID'] . ' typeId=' . $row['ID'] . ' ' . $row['TITLE']);
    $table = 'b_crm_dynamic_items_' . (int)$row['ENTITY_TYPE_ID'];
    $ok = qall($conn, "SHOW TABLES LIKE '" . $table . "'");
    if (!$ok) {
        say('  no table');
        continue;
    }
    $hit = qall($conn, "SELECT ID, TITLE FROM $table WHERE TITLE LIKE 'a7group-%' LIMIT 3");
    $n = qall($conn, "SELECT COUNT(*) n FROM $table WHERE TITLE LIKE 'a7group-%'");
    say('  a7group_titles=' . (int)($n[0]['n'] ?? 0));
    foreach ($hit as $h) {
        say('  HIT ' . $h['ID'] . ' ' . $h['TITLE']);
    }
}

say('== UF STRING COLUMNS mentioning ref on dynamic ==');
foreach (qall($conn, "SELECT ENTITY_ID, FIELD_NAME, USER_TYPE_ID
    FROM b_user_field
    WHERE FIELD_NAME LIKE 'UF_CRM%' AND (
        ENTITY_ID LIKE 'CRM_%'
    ) AND USER_TYPE_ID IN ('string','url')
    LIMIT 5") as $row) {
    // placeholder to keep query valid; real scan below
    break;
}

$ufs = qall($conn, "SELECT f.ENTITY_ID, f.FIELD_NAME
    FROM b_user_field f
    WHERE f.USER_TYPE_ID='string' AND f.ENTITY_ID LIKE 'CRM_%'");
$checked = 0;
foreach ($ufs as $uf) {
    $entity = (string)$uf['ENTITY_ID'];
    $field = (string)$uf['FIELD_NAME'];
    if (!preg_match('/^CRM_(\d+)$/', $entity, $m) && $entity !== 'CRM_DEAL' && $entity !== 'CRM_LEAD') {
        // DYNAMIC entities are CRM_<typeId> sometimes CRM_DYNAMIC_x
    }
    $table = null;
    if ($entity === 'CRM_LEAD') {
        $table = 'b_uts_crm_lead';
    } elseif ($entity === 'CRM_DEAL') {
        $table = 'b_uts_crm_deal';
    } elseif (preg_match('/^CRM_(\d+)$/', $entity, $m)) {
        $table = 'b_uts_crm_dynamic_' . $m[1]; // may be wrong; skip if missing
    } else {
        continue;
    }
    $exists = qall($conn, "SHOW TABLES LIKE '" . $table . "'");
    if (!$exists) {
        continue;
    }
    $col = qall($conn, "SHOW COLUMNS FROM $table LIKE '" . $field . "'");
    if (!$col) {
        continue;
    }
    $checked++;
    $n = qall($conn, "SELECT COUNT(*) n FROM $table WHERE `$field` LIKE 'a7group-%'");
    $c = (int)($n[0]['n'] ?? 0);
    if ($c > 0 && $entity !== 'CRM_LEAD') {
        say('UF_HIT ' . $entity . ' ' . $field . ' n=' . $c);
    }
}
say('UF_SCANNED ' . $checked);
say('DONE');
