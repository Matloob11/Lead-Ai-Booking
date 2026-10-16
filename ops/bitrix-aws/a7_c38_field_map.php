<?php
/**
 * C38: read-only lead field map. CLI only.
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
$sql = $conn->getSqlHelper();

function qall($conn, string $sql): array
{
    $rows = [];
    $res = $conn->query($sql);
    while ($res && ($row = $res->fetch())) {
        $rows[] = $row;
    }
    return $rows;
}

$fields = [
    'UF_CRM_1731838126127',
    'UF_CRM_1760707292',
    'UF_CRM_1763390179',
    'UF_CRM_A7_RENT_SALE',
    'UF_CRM_1756638760279',
    'UF_CRM_LEAD_1737031634747',
    'UF_CRM_1731838790184',
    'UF_CRM_1760707563281',
    'UF_CRM_1760707550978',
    'UF_CRM_1760707872553',
    'UF_CRM_1770537051525',
];
$in = "'" . implode("','", $fields) . "'";
say('== USER FIELDS ==');
foreach (qall($conn, "SELECT f.ID, f.FIELD_NAME, f.USER_TYPE_ID, f.MULTIPLE, f.SETTINGS
    FROM b_user_field f
    WHERE f.ENTITY_ID='CRM_LEAD' AND f.FIELD_NAME IN ($in)
    ORDER BY f.FIELD_NAME") as $row) {
    $settings = (string)($row['SETTINGS'] ?? '');
    if (strlen($settings) > 240) {
        $settings = substr($settings, 0, 240) . '…';
    }
    say('UF id=' . $row['ID'] . ' ' . $row['FIELD_NAME'] . ' type=' . $row['USER_TYPE_ID']
        . ' multi=' . $row['MULTIPLE'] . ' settings=' . $settings);
}

say('== ENUMS ==');
foreach (qall($conn, "SELECT f.FIELD_NAME, e.ID, e.VALUE, e.XML_ID
    FROM b_user_field_enum e
    JOIN b_user_field f ON f.ID=e.USER_FIELD_ID
    WHERE f.ENTITY_ID='CRM_LEAD' AND f.FIELD_NAME IN ($in)
    ORDER BY f.FIELD_NAME, e.SORT, e.ID") as $row) {
    say($row['FIELD_NAME'] . ' ' . $row['ID'] . ' ' . $row['VALUE'] . ' xml=' . $row['XML_ID']);
}

say('== SPA TYPES mentioning property/community ==');
foreach (qall($conn, "SELECT ID, TITLE, NAME FROM b_crm_dynamic_type
    WHERE ID IN (1188) OR TITLE LIKE '%ropert%' OR TITLE LIKE '%ommun%' OR NAME LIKE '%ropert%'
    ORDER BY ID LIMIT 30") as $row) {
    say('TYPE ' . $row['ID'] . ' ' . $row['TITLE'] . ' / ' . $row['NAME']);
}

// Property type items (SPA 1188) — table name convention.
$tables = qall($conn, "SHOW TABLES LIKE 'b_crm_dynamic_items_1188'");
say('SPA1188_TABLE ' . (count($tables) ? 'yes' : 'no'));
if ($tables) {
    say('== PROPERTY TYPE ITEMS (1188) ==');
    foreach (qall($conn, "SELECT ID, TITLE FROM b_crm_dynamic_items_1188 ORDER BY ID") as $row) {
        say('PT ' . $row['ID'] . ' ' . $row['TITLE']);
    }
}

// Sub-community field settings may name another entity type.
$sc = qall($conn, "SELECT SETTINGS FROM b_user_field WHERE ENTITY_ID='CRM_LEAD' AND FIELD_NAME='UF_CRM_1763390179'");
if ($sc) {
    $raw = (string)$sc[0]['SETTINGS'];
    $un = @unserialize($raw);
    say('SUBCOMM_SETTINGS ' . (is_array($un) ? json_encode($un) : substr($raw, 0, 400)));
    $typeId = 0;
    if (is_array($un)) {
        foreach (['DYNAMIC_TYPE_ID', 'entityTypeId', 'ENTITY_TYPE_ID'] as $k) {
            if (!empty($un[$k])) {
                $typeId = (int)$un[$k];
            }
        }
        if (!$typeId && !empty($un['CRM_ENTITY_TYPE'])) {
            say('SUBCOMM_CRM_ENTITY ' . json_encode($un['CRM_ENTITY_TYPE']));
        }
    }
}

say('== IC CLUSTER CANDIDATES ==');
// Search dynamic item tables for International City cluster names is heavy.
// Sample distinct sub-community ids used with community text International City.
$used = qall($conn, "SELECT u.UF_CRM_1763390179 sid, COUNT(*) n
    FROM b_uts_crm_lead u
    JOIN b_crm_lead l ON l.ID=u.VALUE_ID
    WHERE u.UF_CRM_1770537051525='International City'
      AND u.UF_CRM_1763390179 IS NOT NULL AND u.UF_CRM_1763390179<>'' AND u.UF_CRM_1763390179<>'0'
    GROUP BY u.UF_CRM_1763390179
    ORDER BY n DESC
    LIMIT 40");
say('IC_SUBCOMM_DISTINCT ' . count($used));
$ids = [];
foreach ($used as $row) {
    $ids[] = (int)$row['sid'];
    say('SUB_USED id=' . $row['sid'] . ' n=' . $row['n']);
}

// Resolve titles: try common dynamic tables.
foreach ([1186, 1187, 1189, 1190, 1042, 128, 129] as $tid) {
    $t = 'b_crm_dynamic_items_' . $tid;
    $exists = qall($conn, "SHOW TABLES LIKE '" . $t . "'");
    if (!$exists || !$ids) {
        continue;
    }
    $list = implode(',', $ids);
    $hits = qall($conn, "SELECT ID, TITLE FROM $t WHERE ID IN ($list) LIMIT 50");
    if ($hits) {
        say('RESOLVED_IN ' . $t);
        foreach ($hits as $h) {
            say('  ITEM ' . $h['ID'] . ' ' . $h['TITLE']);
        }
    }
}

say('== REF COUNTS ==');
$ref = qall($conn, "SELECT
    SUM(UF_CRM_1760707563281 LIKE 'a7group-%') a7,
    SUM(UF_CRM_1760707563281 IS NOT NULL AND UF_CRM_1760707563281<>'') anyref,
    COUNT(*) total
  FROM b_uts_crm_lead")[0];
say('REF_A7GROUP ' . (int)$ref['a7'] . ' ANY ' . (int)$ref['anyref'] . ' LEADS ' . (int)$ref['total']);

$ic = qall($conn, "SELECT
    COUNT(*) ic,
    SUM(u.UF_CRM_1760707563281 LIKE 'a7group-%') ic_a7,
    SUM(u.UF_CRM_1760707563281 IS NOT NULL AND u.UF_CRM_1760707563281<>'') ic_any
  FROM b_uts_crm_lead u
  WHERE u.UF_CRM_1770537051525='International City'")[0];
say('IC_LEADS ' . (int)$ic['ic'] . ' IC_A7 ' . (int)$ic['ic_a7'] . ' IC_ANYREF ' . (int)$ic['ic_any']);

$one = qall($conn, "SELECT COUNT(*) n FROM b_uts_crm_lead
  WHERE UF_CRM_1760707563281='a7group-1713'")[0];
say('A7GROUP_1713 ' . (int)$one['n']);

$link = qall($conn, "SELECT
    SUM(UF_CRM_1760707550978 IS NOT NULL AND UF_CRM_1760707550978<>'') links,
    SUM(UF_CRM_1760707563281 LIKE 'a7group-%' AND UF_CRM_1760707550978 IS NOT NULL AND UF_CRM_1760707550978<>'') bothn
  FROM b_uts_crm_lead")[0];
say('PROP_LINK_NONEMPTY ' . (int)$link['links'] . ' REF_AND_LINK ' . (int)$link['bothn']);

$sample = qall($conn, "SELECT UF_CRM_1760707563281 ref, UF_CRM_1760707550978 link
  FROM b_uts_crm_lead
  WHERE UF_CRM_1760707563281 LIKE 'a7group-%' AND UF_CRM_1760707550978 IS NOT NULL AND UF_CRM_1760707550978<>''
  LIMIT 3");
foreach ($sample as $s) {
    say('SAMPLE_REF ' . $s['ref'] . ' LINK ' . substr((string)$s['link'], 0, 180));
}

say('== SOURCES ON A7GROUP REFS ==');
foreach (qall($conn, "SELECT l.SOURCE_ID, COUNT(*) n
  FROM b_crm_lead l JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
  WHERE u.UF_CRM_1760707563281 LIKE 'a7group-%'
  GROUP BY l.SOURCE_ID ORDER BY n DESC LIMIT 15") as $row) {
    say('SRC ' . $row['SOURCE_ID'] . ' ' . $row['n']);
}

say('== WRITERS ==');
$roots = [
    '/home/bitrix/www/bitrix/php_interface',
    '/home/bitrix/www/local/php_interface',
    '/home/bitrix/www/bitrix/tools',
];
$needle = 'UF_CRM_1760707563281';
foreach ($roots as $root) {
    if (!is_dir($root)) {
        continue;
    }
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS));
    foreach ($it as $file) {
        if (!$file->isFile() || !str_ends_with($file->getFilename(), '.php')) {
            continue;
        }
        if ($file->getSize() > 800000) {
            continue;
        }
        $txt = @file_get_contents($file->getPathname());
        if ($txt !== false && str_contains($txt, $needle)) {
            say('FILE ' . $file->getPathname());
        }
    }
}
say('DONE');
