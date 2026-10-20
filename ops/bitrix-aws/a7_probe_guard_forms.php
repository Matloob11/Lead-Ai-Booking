<?php
/**
 * Read-only probe for the booking-fields fix: which commission fields the lead form shows (and in which
 * section), how the lead details component hands file user fields to CCrmLead::Update, and what
 * CCrmLead::GetListEx returns for file fields on two leads. Stub with _stub404.php after use.
 *
 * Run: ops/bitrix.sh run a7_probe_guard_forms.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

function say(string $line): void
{
    echo $line, "\n";
}

$want = ['UF_CRM_A7_COMM_DOC', 'UF_CRM_A7_COMM_ZONE', 'UF_CRM_A7_COMM_STATUS', 'UF_CRM_A7_COMM_REF', 'UF_CRM_A7_DEAL_TYPE',
    'UF_CRM_A7_BOOKING_RENT_SALE', 'UF_CRM_A7_COMMISSION_ZONE', 'UF_CRM_A7_COMMISSION_DOC', 'UF_CRM_A7_COMMISSION_STATUS',
    'UF_CRM_A7_COMMISSION_VOUCHER', 'UF_CRM_A7_TRADE_LICENSE_FILE', 'UF_CRM_1758005814661'];

function walk($node, string $section, array &$found): void
{
    if (!is_array($node)) {
        return;
    }
    if (($node['type'] ?? '') === 'section' || isset($node['elements'])) {
        $section = (string) ($node['title'] ?? $node['name'] ?? $section);
    }
    if (isset($node['name']) && is_string($node['name'])) {
        $found[$node['name']][] = $section;
    }
    foreach ($node as $child) {
        if (is_array($child)) {
            walk($child, $section, $found);
        }
    }
}

$conn = \Bitrix\Main\Application::getConnection();
say('--- editor configs (b_ui_entity_editor_config lead_details) ---');
$rs = $conn->query("SELECT ID, NAME, CONFIG FROM b_ui_entity_editor_config WHERE ENTITY_TYPE_ID='lead_details' ORDER BY ID");
while ($row = $rs->fetch()) {
    $cfg = @unserialize((string) $row['CONFIG'], ['allowed_classes' => false]);
    $found = [];
    walk($cfg, '', $found);
    $hits = [];
    foreach ($want as $name) {
        if (isset($found[$name])) {
            $hits[] = $name . ' in [' . implode('|', array_unique($found[$name])) . ']';
        }
    }
    say('config ' . $row['ID'] . ' ' . $row['NAME'] . ': ' . ($hits ? implode('; ', $hits) : '(none of them)'));
}
say('--- user options (crm.entity.editor lead_details) ---');
$rs = $conn->query("SELECT ID, USER_ID, NAME, VALUE FROM b_user_option WHERE CATEGORY='crm.entity.editor' AND NAME IN ('lead_details','lead_details_common') ORDER BY ID");
$n = 0;
while ($row = $rs->fetch()) {
    $cfg = @unserialize((string) $row['VALUE'], ['allowed_classes' => false]);
    $found = [];
    walk($cfg, '', $found);
    $hits = [];
    foreach ($want as $name) {
        if (isset($found[$name])) {
            $hits[] = $name . ' in [' . implode('|', array_unique($found[$name])) . ']';
        }
    }
    if ($hits && $n < 12) {
        say('option ' . $row['ID'] . ' ' . $row['NAME'] . ' user=' . $row['USER_ID'] . ': ' . implode('; ', $hits));
    }
    $n += $hits ? 1 : 0;
}
say('options with any of them: ' . $n);

say('--- how the lead details component handles file user fields ---');
foreach (['/bitrix/components/bitrix/crm.lead.details/ajax.php', '/bitrix/components/bitrix/crm.lead.details/class.php',
    '/bitrix/modules/crm/lib/component/entitydetails/basecomponent.php'] as $path) {
    $full = $_SERVER['DOCUMENT_ROOT'] . $path;
    if (!is_file($full)) {
        say($path . ': missing');
        continue;
    }
    $lines = file($full, FILE_IGNORE_NEW_LINES) ?: [];
    say($path . ' (' . count($lines) . ' lines)');
    foreach ($lines as $i => $line) {
        if (preg_match('~(_FILES|prepareFileFields|FileFields|USER_TYPE_ID.{0,20}file|old_id|\bdel\b.*file|file.*\bdel\b)~i', $line)) {
            say(sprintf('  %5d: %s', $i + 1, trim($line)));
        }
    }
}

say('--- GetListEx values for file fields on leads 73331 and 79223 ---');
foreach ([73331, 79223, 78387] as $id) {
    $rs = \CCrmLead::GetListEx([], ['=ID' => $id, 'CHECK_PERMISSIONS' => 'N'], false, false, ['ID', 'STATUS_ID', 'UF_CRM_A7_COMM_DOC', 'UF_CRM_A7_COMMISSION_DOC', 'UF_CRM_A7_TRADE_LICENSE_FILE', 'UF_CRM_1758005814661']);
    $row = $rs ? $rs->Fetch() : null;
    say($id . ': ' . json_encode($row, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
}
say('DONE');
