<?php
/**
 * C36: after BP 235 skip extends to 2478 — prove a person's meeting on a
 * Handed-to-agent lead survives a UI edit, and a normal stage-10 lead with
 * no Bot Status is still wiped. CLI only. Deletes both test leads.
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

function say(string $line): void
{
    echo $line, "\n";
}

function snap($factory, $conn, int $leadId, string $label): array
{
    $fresh = $factory->getItem($leadId);
    $meet = $conn->query(
        "SELECT UF_CRM_1731838813769 M, UF_CRM_A7_BOT_STATUS BOT FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}"
    )->fetch();
    $meeting = is_array($meet) ? (string)$meet['M'] : '';
    $bot = is_array($meet) ? (string)$meet['BOT'] : '';
    $stage = $fresh ? (string)$fresh->getStageId() : '';
    $open = 0;
    $rows = $conn->query(
        "SELECT a.ID, a.DEADLINE, a.COMPLETED, a.SUBJECT, a.RESPONSIBLE_ID
         FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
         WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId} AND a.PROVIDER_ID='CRM_TODO' AND a.COMPLETED='N'"
    );
    while ($rows && ($row = $rows->fetch())) {
        $open++;
        say("  TODO {$row['ID']} {$row['DEADLINE']} resp={$row['RESPONSIBLE_ID']}");
    }
    say('SNAP ' . $label . ' stage=' . $stage
        . ' meet=' . ($meeting === '' ? '(empty)' : $meeting)
        . ' bot=' . $bot . ' open=' . $open);
    return compact('meeting', 'bot', 'stage', 'open');
}

function wipe($factory, $conn, $context, int $leadId): void
{
    $ids = $conn->query(
        "SELECT a.ID FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
         WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId}"
    );
    while ($ids && ($row = $ids->fetch())) {
        $conn->queryExecute('DELETE FROM b_crm_act_bind WHERE ACTIVITY_ID=' . (int)$row['ID']);
        $conn->queryExecute('DELETE FROM b_crm_act WHERE ID=' . (int)$row['ID']);
    }
    $item = $factory->getItem($leadId);
    if ($item !== null) {
        $del = $factory->getDeleteOperation($item, $context);
        $del->disableCheckAccess();
        $del->disableBizProc();
        $del->disableAutomation();
        $del->launch();
    }
}

\Bitrix\Main\Loader::includeModule('crm');
global $USER;
if (!is_object($USER)) {
    $USER = new CUser();
}
$USER->Authorize(1);

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$conn = \Bitrix\Main\Application::getConnection();

// --- A: person handoff (Bot Status 2478) + meeting must survive a UI edit ---
$item = $factory->createItem([
    'TITLE' => 'ZZ C36 person 2478 survive delete',
    'NAME' => 'Person',
    'LAST_NAME' => 'Meet',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'IN_PROCESS',
]);
$add = $factory->getAddOperation($item, $context);
$add->disableCheckAccess();
$add->disableBizProc();
$add->disableAutomation();
$add->launch();
$handLead = (int)$item->getId();
say('HAND_LEAD ' . $handLead);

$h = $factory->getItem($handLead);
$h->setStageId('10');
$h->set('UF_CRM_A7_BOT_STATUS', 2478);
$h->set('UF_CRM_1731838813769', new \Bitrix\Main\Type\DateTime('2026-11-06 13:00:00', 'Y-m-d H:i:s'));
$up = $factory->getUpdateOperation($h, $context);
$up->disableCheckAccess();
$up->disableBizProc();
$up->disableAutomation();
$up->launch();
$before = snap($factory, $conn, $handLead, 'hand_before_edit');

$fresh = $factory->getItem($handLead);
$fresh->set('COMMENTS', 'c36-prove-hand-edit');
$op = $factory->getUpdateOperation($fresh, $context);
$op->disableCheckAccess();
$op->launch(); // bizproc ON — BP 235 must skip wipe
$after = snap($factory, $conn, $handLead, 'hand_after_edit');
$handOk = ($after['meeting'] !== '' && $after['meeting'] === $before['meeting']);
say('HAND_SURVIVED ' . ($handOk ? 'yes' : 'no'));

// --- B: normal stage-10 lead without Bot Status still wiped ---
$item2 = $factory->createItem([
    'TITLE' => 'ZZ C36 normal stage10 delete',
    'NAME' => 'Norm',
    'LAST_NAME' => 'Wipe',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'IN_PROCESS',
]);
$add2 = $factory->getAddOperation($item2, $context);
$add2->disableCheckAccess();
$add2->disableBizProc();
$add2->disableAutomation();
$add2->launch();
$normLead = (int)$item2->getId();
say('NORM_LEAD ' . $normLead);

// C6 flag: C36 must not stamp 2478 on this setup write (we need empty Bot Status).
$GLOBALS['A7_LEADAI_FIELDS_SAVE'] = $normLead;
$n = $factory->getItem($normLead);
$n->setStageId('10');
$n->set('UF_CRM_A7_BOT_STATUS', null);
$n->set('UF_CRM_1731838813769', new \Bitrix\Main\Type\DateTime('2026-11-05 15:00:00', 'Y-m-d H:i:s'));
$up2 = $factory->getUpdateOperation($n, $context);
$up2->disableCheckAccess();
$up2->disableBizProc();
$up2->disableAutomation();
$up2->launch();
unset($GLOBALS['A7_LEADAI_FIELDS_SAVE']);
$nb = snap($factory, $conn, $normLead, 'norm_before_edit');
if ((string)$nb['bot'] !== '' && (int)$nb['bot'] !== 0) {
    say('NORM_SETUP_BOT_NOT_EMPTY');
}

$n2 = $factory->getItem($normLead);
$n2->set('COMMENTS', 'c36-prove-norm-edit');
$op2 = $factory->getUpdateOperation($n2, $context);
$op2->disableCheckAccess();
$op2->launch();
$na = snap($factory, $conn, $normLead, 'norm_after_edit');
$normWiped = ($na['meeting'] === '' && $na['open'] >= 1);
say('NORM_WIPED_AS_BEFORE ' . ($normWiped ? 'yes' : 'no'));
say('NORM_OPEN_TODOS ' . $na['open']);

wipe($factory, $conn, $context, $handLead);
wipe($factory, $conn, $context, $normLead);
say('DELETED hand=' . ($factory->getItem($handLead) === null ? 'yes' : 'no')
    . ' norm=' . ($factory->getItem($normLead) === null ? 'yes' : 'no'));
say('PASS ' . ($handOk && $normWiped ? 'yes' : 'no'));
say('DONE');
