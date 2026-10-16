<?php
/**
 * C39: residential lead fields + Lead AI form section. CLI only.
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
\Bitrix\Main\Loader::includeModule('crm');

if (class_exists('A7PortalLeadFields')) {
    $ref = new ReflectionClass('A7PortalLeadFields');
    if ($ref->hasProperty('allowed')) {
        $prop = $ref->getProperty('allowed');
        $prop->setAccessible(true);
        $prop->setValue(null, true);
    }
}

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
function ensureField(string $name, string $type, string $label): int
{
    global $APPLICATION;
    $existing = fieldRow($name);
    if ($existing) {
        say("EXISTS {$name} id={$existing['ID']}");
        return (int)$existing['ID'];
    }
    if (is_object($APPLICATION)) {
        $APPLICATION->ResetException();
    }
    $entity = new CUserTypeEntity();
    $id = (int)$entity->Add([
        'ENTITY_ID' => 'CRM_LEAD',
        'FIELD_NAME' => $name,
        'USER_TYPE_ID' => $type,
        'XML_ID' => $name,
        'SORT' => 530,
        'MULTIPLE' => 'N',
        'MANDATORY' => 'N',
        'SHOW_FILTER' => 'I',
        'SHOW_IN_LIST' => 'Y',
        'EDIT_IN_LIST' => 'Y',
        'IS_SEARCHABLE' => 'N',
        'SETTINGS' => $type === 'enumeration'
            ? ['DISPLAY' => 'LIST', 'LIST_HEIGHT' => 1, 'CAPTION_NO_VALUE' => '', 'SHOW_NO_VALUE' => 'Y']
            : ['SIZE' => 40, 'ROWS' => 1, 'REGEXP' => '', 'MIN_LENGTH' => 0, 'MAX_LENGTH' => 0, 'DEFAULT_VALUE' => ''],
        'EDIT_FORM_LABEL' => labels($label),
        'LIST_COLUMN_LABEL' => labels($label),
        'LIST_FILTER_LABEL' => labels($label),
    ]);
    if ($id <= 0) {
        $ex = is_object($APPLICATION) ? $APPLICATION->GetException() : null;
        say('FAIL ' . $name . ' ' . ($ex ? $ex->GetString() : '?'));
        exit(1);
    }
    say("CREATED {$name} id={$id}");
    return $id;
}
function ensureEnums(int $fieldId, array $wanted): void
{
    $have = [];
    global $conn;
    $rs = $conn->query("SELECT ID, VALUE, SORT FROM b_user_field_enum WHERE USER_FIELD_ID={$fieldId}");
    while ($rs && ($row = $rs->fetch())) {
        $have[strtolower(trim((string)$row['VALUE']))] = $row;
    }
    $payload = [];
    foreach ($have as $row) {
        $payload[$row['ID']] = ['ID' => $row['ID'], 'VALUE' => $row['VALUE'], 'SORT' => $row['SORT'], 'DEF' => 'N'];
    }
    $i = 0;
    $added = [];
    foreach ($wanted as $value => $sort) {
        if (!isset($have[strtolower($value)])) {
            $payload['n' . $i] = ['VALUE' => $value, 'SORT' => $sort, 'DEF' => 'N'];
            $added[] = $value;
            $i++;
        }
    }
    if ($added) {
        $enum = new CUserFieldEnum();
        if (!$enum->SetEnumValues($fieldId, $payload)) {
            say('ENUM FAIL ' . $fieldId);
            exit(1);
        }
        say('ENUMS ' . $fieldId . ' ' . implode(',', $added));
    }
}

$enumFields = [
    'UF_CRM_A7_BALCONY' => ['Balcony', ['Yes' => 100, 'No' => 200, 'Either' => 300]],
    'UF_CRM_A7_VACANT_RENTED' => ['Vacant or rented', ['Vacant' => 100, 'Rented' => 200, 'Either' => 300]],
    'UF_CRM_A7_PAYMENT' => ['Payment', ['Cash' => 100, 'Mortgage' => 200]],
    'UF_CRM_A7_OCCUPANCY' => ['Occupancy', ['Myself' => 100, 'Family' => 200, 'Company staff' => 300, 'Sharing' => 400]],
];
$textFields = [
    'UF_CRM_A7_CLUSTERS' => 'Clusters',
    'UF_CRM_A7_TIMELINE' => 'Timeline',
    'UF_CRM_A7_FULL_NAME' => 'Full name',
];
$names = [];
foreach ($textFields as $code => $label) {
    ensureField($code, 'string', $label);
    $names[] = $code;
}
foreach ($enumFields as $code => $spec) {
    $id = ensureField($code, 'enumeration', $spec[0]);
    ensureEnums($id, $spec[1]);
    $names[] = $code;
}

say('--- IDS ---');
foreach (array_merge(array_keys($textFields), array_keys($enumFields)) as $code) {
    $row = fieldRow($code);
    say('FIELD ' . $code . ' id=' . ($row['ID'] ?? ''));
    if (($row['USER_TYPE_ID'] ?? '') === 'enumeration') {
        $rs = $conn->query('SELECT ID, VALUE FROM b_user_field_enum WHERE USER_FIELD_ID=' . (int)$row['ID'] . ' ORDER BY SORT');
        while ($rs && ($e = $rs->fetch())) {
            say('  ENUM ' . $e['ID'] . ' ' . $e['VALUE']);
        }
    }
}

function placeFields($cfg, array $fieldNames)
{
    if (!is_array($cfg)) {
        return $cfg;
    }
    $found = false;
    $walk = function (&$node) use (&$walk, $fieldNames, &$found) {
        if (!is_array($node)) {
            return;
        }
        if (($node['type'] ?? '') === 'section' && ($node['name'] ?? '') === 'a7_shops_bot') {
            $found = true;
            $node['title'] = 'Lead AI';
            $have = [];
            foreach ($node['elements'] ?? [] as $el) {
                if (isset($el['name'])) {
                    $have[$el['name']] = true;
                }
            }
            foreach ($fieldNames as $name) {
                if (!isset($have[$name])) {
                    $node['elements'][] = ['name' => $name, 'optionFlags' => '1'];
                }
            }
        }
        foreach ($node as &$child) {
            if (is_array($child)) {
                $walk($child);
            }
        }
    };
    $walk($cfg);
    if (!$found && isset($cfg[0]['elements']) && is_array($cfg[0]['elements'])) {
        $els = [];
        foreach ($fieldNames as $name) {
            $els[] = ['name' => $name, 'optionFlags' => '1'];
        }
        $cfg[0]['elements'][] = [
            'name' => 'a7_shops_bot',
            'title' => 'Lead AI',
            'type' => 'section',
            'elements' => $els,
        ];
    }
    return $cfg;
}

$backup = '/home/bitrix/a7_c39_form_bak_' . date('Ymd_His');
mkdir($backup, 0755, true);
$common = $conn->query(
    "SELECT VALUE FROM b_user_option WHERE USER_ID=0 AND CATEGORY='crm.entity.editor' AND NAME='lead_details_common' LIMIT 1"
)->fetch();
if (is_array($common)) {
    file_put_contents($backup . '/lead_details_common.ser', (string)$common['VALUE']);
    $cfg = @unserialize((string)$common['VALUE'], ['allowed_classes' => false]);
    if (is_array($cfg)) {
        \CUserOptions::SetOption('crm.entity.editor', 'lead_details_common', placeFields($cfg, $names), true, 0);
        say('FORM common updated');
    }
}
say('BACKUP ' . $backup);
say('DONE');
