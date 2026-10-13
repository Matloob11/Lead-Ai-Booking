<?php
/**
 * International City shops lead fields (C3). Idempotent.
 * Creates the missing CRM_LEAD fields, adds the licence and Broker values,
 * and puts the shops fields on the lead form without removing what is there.
 *
 * Run: ops/bitrix.sh run a7_shops_lead_fields.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

\Bitrix\Main\Loader::includeModule('crm');

$conn = \Bitrix\Main\Application::getConnection();
$sql = $conn->getSqlHelper();
global $APPLICATION;

function say(string $line): void
{
    echo $line, "\n";
}

function labels(string $text): array
{
    $out = [];
    foreach (['en', 'br', 'fr', 'it', 'la', 'pl', 'ua'] as $lang) {
        $out[$lang] = $text;
    }
    return $out;
}

function fieldRow(string $name): ?array
{
    global $conn, $sql;
    $safe = $sql->forSql($name);
    $row = $conn->query(
        "SELECT ID, USER_TYPE_ID FROM b_user_field WHERE ENTITY_ID='CRM_LEAD' AND FIELD_NAME='{$safe}'"
    )->fetch();
    return is_array($row) ? $row : null;
}

function enumMap(int $fieldId): array
{
    global $conn;
    $out = [];
    if ($fieldId <= 0) {
        return $out;
    }
    $rs = $conn->query(
        "SELECT ID, VALUE, SORT FROM b_user_field_enum WHERE USER_FIELD_ID={$fieldId} ORDER BY SORT, ID"
    );
    while ($rs && ($row = $rs->fetch())) {
        $out[trim((string)$row['VALUE'])] = ['id' => (int)$row['ID'], 'sort' => (int)$row['SORT']];
    }
    return $out;
}

function ensureField(string $name, string $type, string $label, string $xmlId, array $settings): int
{
    global $APPLICATION;
    $existing = fieldRow($name);
    if ($existing) {
        say("field {$name} exists id={$existing['ID']} type={$existing['USER_TYPE_ID']}");
        return (int)$existing['ID'];
    }
    if (is_object($APPLICATION) && method_exists($APPLICATION, 'ResetException')) {
        $APPLICATION->ResetException();
    }
    $entity = new CUserTypeEntity();
    $id = (int)$entity->Add([
        'ENTITY_ID' => 'CRM_LEAD',
        'FIELD_NAME' => $name,
        'USER_TYPE_ID' => $type,
        'XML_ID' => $xmlId,
        'SORT' => 520,
        'MULTIPLE' => 'N',
        'MANDATORY' => 'N',
        'SHOW_FILTER' => 'I',
        'SHOW_IN_LIST' => 'Y',
        'EDIT_IN_LIST' => 'Y',
        'IS_SEARCHABLE' => 'N',
        'SETTINGS' => $settings,
        'EDIT_FORM_LABEL' => labels($label),
        'LIST_COLUMN_LABEL' => labels($label),
        'LIST_FILTER_LABEL' => labels($label),
        'ERROR_MESSAGE' => labels(''),
        'HELP_MESSAGE' => labels(''),
    ]);
    if ($id <= 0) {
        $ex = is_object($APPLICATION) ? $APPLICATION->GetException() : null;
        say('CREATE FAILED ' . $name . ': ' . ($ex ? $ex->GetString() : '?'));
        exit(1);
    }
    say("field {$name} created id={$id} type={$type}");
    return $id;
}

function ensureEnums(int $fieldId, array $wanted): void
{
    $have = enumMap($fieldId);
    $lower = [];
    foreach ($have as $value => $meta) {
        $lower[strtolower($value)] = $value;
    }
    $missing = [];
    foreach ($wanted as $value => $sort) {
        if (!isset($lower[strtolower($value)])) {
            $missing[$value] = $sort;
        }
    }
    if (!$missing) {
        return;
    }
    $payload = [];
    foreach ($have as $value => $meta) {
        $payload[$meta['id']] = [
            'ID' => $meta['id'],
            'VALUE' => $value,
            'SORT' => $meta['sort'],
            'DEF' => 'N',
        ];
    }
    $i = 0;
    foreach ($missing as $value => $sort) {
        $payload['n' . $i] = ['VALUE' => $value, 'SORT' => $sort, 'DEF' => 'N'];
        $i++;
    }
    $enum = new CUserFieldEnum();
    if (!$enum->SetEnumValues($fieldId, $payload)) {
        say("SetEnumValues FAILED for field {$fieldId}");
        exit(1);
    }
    say('added enums on ' . $fieldId . ': ' . implode(', ', array_keys($missing)));
}

function printEnums(string $name): void
{
    $row = fieldRow($name);
    if (!$row) {
        say("MISSING {$name}");
        return;
    }
    say("MAP {$name} id={$row['ID']} type={$row['USER_TYPE_ID']}");
    foreach (enumMap((int)$row['ID']) as $value => $meta) {
        say("  enum {$meta['id']} {$value}");
    }
}

$enumSettings = [
    'DISPLAY' => 'LIST',
    'LIST_HEIGHT' => 1,
    'CAPTION_NO_VALUE' => '',
    'SHOW_NO_VALUE' => 'Y',
];
$fileSettings = [
    'SIZE' => 20,
    'LIST_WIDTH' => 0,
    'LIST_HEIGHT' => 0,
    'MAX_SHOW_SIZE' => 0,
    'MAX_ALLOWED_SIZE' => 0,
    'EXTENSIONS' => [],
];

$licence = fieldRow('UF_CRM_A7_AI_TRADE_LICENSE_STATUS');
if ($licence) {
    ensureEnums((int)$licence['ID'], [
        'DED' => 300,
        'Trakhees' => 400,
        'New licence' => 500,
    ]);
}

$purpose = fieldRow('UF_CRM_LEAD_1737031634747');
if ($purpose) {
    ensureEnums((int)$purpose['ID'], ['Broker' => 900]);
}

$shop = ensureField('UF_CRM_A7_SHOP_TYPE', 'enumeration', 'Shop Type Wanted', 'A7_SHOP_TYPE', $enumSettings);
ensureEnums($shop, ['Type 1' => 100, 'Type 2' => 200, 'Type 3' => 300, 'Not sure' => 400]);

ensureField('UF_CRM_A7_TRADE_LICENSE_FILE', 'file', 'Trade License File', 'A7_TRADE_LICENSE_FILE', $fileSettings);

$bot = ensureField('UF_CRM_A7_BOT_STATUS', 'enumeration', 'Bot Status', 'A7_BOT_STATUS', $enumSettings);
ensureEnums($bot, [
    'New' => 100,
    'Qualifying' => 200,
    'Viewing booked' => 300,
    'Handed to agent' => 400,
    'Broker' => 500,
    'Lost' => 600,
    'Opted out' => 700,
]);

$opt = ensureField('UF_CRM_A7_WA_OPT_OUT', 'enumeration', 'WhatsApp Opt-out', 'A7_WA_OPT_OUT', $enumSettings);
ensureEnums($opt, ['Yes' => 100, 'No' => 200]);

$shopsFields = [
    'UF_CRM_LEAD_1737031634747',
    'UF_CRM_A7_AI_BUSINESS_ACTIVITY',
    'UF_CRM_A7_AI_TRADE_LICENSE_STATUS',
    'UF_CRM_A7_TRADE_LICENSE_FILE',
    'UF_CRM_A7_SHOP_TYPE',
    'UF_CRM_A7_BOT_STATUS',
    'UF_CRM_A7_WA_OPT_OUT',
];

function collectNames($node, array &$names): void
{
    if (!is_array($node)) {
        return;
    }
    if (isset($node['name']) && is_string($node['name']) && ($node['type'] ?? '') !== 'section' && ($node['type'] ?? '') !== 'column') {
        $names[$node['name']] = true;
    }
    foreach ($node as $child) {
        if (is_array($child)) {
            collectNames($child, $names);
        }
    }
}

function appendShops($cfg, array $fieldNames): array
{
    if (!is_array($cfg)) {
        return $cfg;
    }
    $names = [];
    collectNames($cfg, $names);
    $add = [];
    foreach ($fieldNames as $name) {
        if (!isset($names[$name])) {
            $add[] = ['name' => $name, 'optionFlags' => '1'];
        }
    }
    if (!$add) {
        return $cfg;
    }
    $section = [
        'name' => 'a7_shops_bot',
        'title' => 'Shops bot',
        'type' => 'section',
        'elements' => $add,
    ];
    if (isset($cfg[0]['elements']) && is_array($cfg[0]['elements'])) {
        $cfg[0]['elements'][] = $section;
        return $cfg;
    }
    return $cfg;
}

function saveOption(string $category, string $name, $value, int $userId, bool $common): void
{
    if (!class_exists('CUserOptions')) {
        say("no CUserOptions for {$name}");
        return;
    }
    \CUserOptions::SetOption($category, $name, $value, $common, $userId);
    say("saved {$category}/{$name} user={$userId}");
}

$backup = '/home/bitrix/a7_shops_form_bak_' . date('Ymd_His');
if (!mkdir($backup, 0755, true) && !is_dir($backup)) {
    say('backup dir failed');
    exit(1);
}

$common = $conn->query(
    "SELECT ID, VALUE FROM b_user_option WHERE USER_ID=0 AND CATEGORY='crm.entity.editor' AND NAME='lead_details_common' LIMIT 1"
)->fetch();
if (is_array($common) && $common['VALUE'] !== '') {
    file_put_contents($backup . '/lead_details_common.ser', $common['VALUE']);
    $cfg = @unserialize($common['VALUE'], ['allowed_classes' => false]);
    if (is_array($cfg)) {
        $next = appendShops($cfg, $shopsFields);
        saveOption('crm.entity.editor', 'lead_details_common', $next, 0, true);
    } else {
        say('common form did not unserialize');
    }
} else {
    say('lead_details_common missing');
}

$personal = $conn->query(
    "SELECT ID, VALUE FROM b_user_option WHERE USER_ID=1 AND CATEGORY='crm.entity.editor' AND NAME='lead_details' LIMIT 1"
)->fetch();
if (is_array($personal) && $personal['VALUE'] !== '') {
    file_put_contents($backup . '/user1_lead_details.ser', $personal['VALUE']);
    $cfg = @unserialize($personal['VALUE'], ['allowed_classes' => false]);
    if (is_array($cfg)) {
        saveOption('crm.entity.editor', 'lead_details', appendShops($cfg, $shopsFields), 1, false);
    }
}

$configs = $conn->query("SELECT ID, NAME, CONFIG FROM b_ui_entity_editor_config WHERE ENTITY_TYPE_ID='lead_details'");
while ($configs && ($row = $configs->fetch())) {
    file_put_contents($backup . '/editor_' . (int)$row['ID'] . '.ser', (string)$row['CONFIG']);
    $cfg = @unserialize((string)$row['CONFIG'], ['allowed_classes' => false]);
    if (!is_array($cfg)) {
        say('editor config ' . $row['ID'] . ' did not unserialize');
        continue;
    }
    $next = appendShops($cfg, $shopsFields);
    $packed = $sql->forSql(serialize($next));
    $conn->queryExecute(
        "UPDATE b_ui_entity_editor_config SET CONFIG='{$packed}' WHERE ID=" . (int)$row['ID']
    );
    say('updated editor config ' . $row['ID'] . ' ' . $row['NAME']);
}
say('backup ' . $backup);

say('--- field map ---');
foreach ([
    'UF_CRM_LEAD_1737031634747',
    'UF_CRM_A7_AI_BUSINESS_ACTIVITY',
    'UF_CRM_A7_AI_TRADE_LICENSE_STATUS',
    'UF_CRM_1731838813769',
    'UF_CRM_A7_SHOP_TYPE',
    'UF_CRM_A7_TRADE_LICENSE_FILE',
    'UF_CRM_A7_BOT_STATUS',
    'UF_CRM_A7_WA_OPT_OUT',
] as $name) {
    printEnums($name);
}

say('--- lost stages ---');
$statuses = $conn->query(
    "SELECT STATUS_ID, NAME, SEMANTICS FROM b_crm_status
     WHERE ENTITY_ID='STATUS'
       AND (STATUS_ID IN ('JUNK','UC_RYQD1Z')
            OR NAME LIKE '%Reject%'
            OR NAME LIKE '%Not interest%'
            OR NAME LIKE '%Junk%')"
);
while ($statuses && ($row = $statuses->fetch())) {
    say('stage ' . $row['STATUS_ID'] . ' | ' . $row['NAME'] . ' | ' . $row['SEMANTICS']);
}

say('--- stage required fields ---');
$cols = [];
$colRs = $conn->query('SHOW COLUMNS FROM b_crm_field_attr');
while ($colRs && ($col = $colRs->fetch())) {
    $cols[] = $col['Field'];
}
say('attr columns: ' . implode(',', $cols));
$attr = $conn->query("SELECT * FROM b_crm_field_attr WHERE ENTITY_TYPE_ID=1");
while ($attr && ($row = $attr->fetch())) {
    $blob = strtolower(implode(' ', array_map('strval', $row)));
    if (!preg_match('/junk|uc_ryqd1z|reject/', $blob)) {
        continue;
    }
    $parts = [];
    foreach ($row as $key => $value) {
        if ($value !== null && $value !== '') {
            $parts[] = $key . '=' . $value;
        }
    }
    say('attr ' . implode(' ', $parts));
}

say('DONE');
