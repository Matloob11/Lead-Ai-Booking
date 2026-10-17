<?php
/**
 * C41 proof. One test lead, two timeline comments with the same To, one
 * with a different template. The day count is unique To numbers. Then the
 * comments and the lead are deleted. CLI only. Sends nothing.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('A7_LEAD_WA_LIB_ONLY', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/tools/a7_lead_wa.php';

function say(string $line): void
{
    echo $line, "\n";
}

\Bitrix\Main\Loader::includeModule('crm');
global $USER, $DB;
if (!is_object($USER)) {
    $USER = new CUser();
}
$USER->Authorize(1);

$template = 'a7_c41_probe_template';
$other = 'a7_c41_probe_other';
$from = '971581058719';
$to = '971500000041';
$crm = new \CCrmLead(false);
$fields = [
    'TITLE' => 'ZZ C41 proof delete',
    'NAME' => 'C41',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'NEW',
];
$opts = ['CURRENT_USER' => 1];
$leadId = (int)$crm->Add($fields, true, $opts);
say('LEAD ' . $leadId);
if ($leadId <= 0) {
    say('ADD_FAIL ' . $crm->LAST_ERROR);
    exit(1);
}

$before = a7_lead_wa_marketing_sent_today($template, $from);
$ids = [];
foreach ([$template, $template, $other] as $name) {
    $text = "WhatsApp message\nTemplate: {$name}\nFrom: +{$from}\nTo: +{$to}\n\nprobe\n\nCampaign: C41 proof";
    $ids[] = (int)\Bitrix\Crm\Timeline\CommentEntry::create([
        'TEXT' => $text,
        'AUTHOR_ID' => 1,
        'SETTINGS' => [],
        'BINDINGS' => [['ENTITY_TYPE_ID' => \CCrmOwnerType::Lead, 'ENTITY_ID' => $leadId]],
    ]);
}
$after = a7_lead_wa_marketing_sent_today($template, $from);
$otherCount = a7_lead_wa_marketing_sent_today($other, $from);
say('BEFORE ' . $before . ' AFTER ' . $after . ' OTHER ' . $otherCount . ' NOTES ' . implode(',', $ids));
$ok = ($after === $before + 1) && ($otherCount >= 1);

foreach ($ids as $id) {
    if ($id > 0) {
        $DB->Query('DELETE FROM b_crm_timeline_bind WHERE OWNER_ID = ' . $id);
        $DB->Query('DELETE FROM b_crm_timeline WHERE ID = ' . $id);
    }
}
$gone = a7_lead_wa_marketing_sent_today($template, $from);
$leadGone = $crm->Delete($leadId);
$still = \CCrmLead::GetByID($leadId, false);
say('GONE ' . $gone . ' LEAD_DELETE ' . ($leadGone ? '1' : '0') . ' STILL ' . (is_array($still) ? '1' : '0'));
if (!$ok || $gone !== $before || !$leadGone || is_array($still)) {
    exit(1);
}
say('C41_PROOF_OK');
