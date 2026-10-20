<?php
/**
 * Read-only proof of guard 1.5.0 on the live code, with no login as anyone and no write to any lead:
 *  1. the file-field comparison on the shapes the lead form sends (reflection on A7LeadGuard's private helpers);
 *  2. the booking-only decision for the (user, lead) pairs the guard log refused, as permission reads by user id;
 *  3. the guard log's last lines after the deploy (errors would show there).
 * Stub with _stub404.php after use. Run: ops/bitrix.sh run a7_probe_guard_booking.php
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

$fails = 0;
function check(string $what, bool $ok): void
{
    global $fails;
    $fails += $ok ? 0 : 1;
    say(($ok ? 'PASS ' : 'FAIL ') . $what);
}

if (!class_exists('A7LeadGuard')) {
    require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_lead_guard.php';
}
say('guard version ' . A7LeadGuard::VERSION . ', perms loaded: ' . (A7LeadGuard::perms() ? 'yes' : 'NO'));
check('guard is 1.5.0', A7LeadGuard::VERSION === '1.5.0');
check('perms class has the booking grant', method_exists('A7LeadShare', 'bookingOnly') && method_exists('A7LeadShare', 'bookingGrant'));
say('booking fields: ' . implode(', ', A7LeadShare::bookingFields()));

// 1. the comparison helpers, on synthetic values (nothing is written)
$ref = new \ReflectionClass('A7LeadGuard');
$call = static function (string $method, ...$args) use ($ref) {
    $m = $ref->getMethod($method);
    $m->setAccessible(true);
    return $m->invoke(null, ...$args);
};
$emptySlot = ['name' => '', 'type' => '', 'tmp_name' => '', 'error' => 4, 'size' => 0];
$upload = ['name' => 'licence.pdf', 'type' => 'application/pdf', 'tmp_name' => '/tmp/phpAbc', 'error' => 0, 'size' => 1234];
check('empty upload slot against no file: unchanged', $call('fileChanged', null, $emptySlot) === false);
check('empty upload slot against a stored file: unchanged', $call('fileChanged', 198973, $emptySlot) === false);
check('nested empty slot (n0) against a stored file: unchanged', $call('fileChanged', '198973', ['n0' => $emptySlot]) === false);
check('stored false (multiple, none) against nothing: unchanged', $call('fileChanged', false, []) === false);
check('a real upload: changed', $call('fileChanged', null, $upload) === true);
check('a real upload over a stored file: changed', $call('fileChanged', 198973, $upload) === true);
check('a delete flag: changed', $call('fileChanged', 198973, $emptySlot + ['del' => 'Y', 'old_file' => 198973]) === true);
check('the same file kept (old_file): unchanged', $call('fileChanged', 198973, $emptySlot + ['old_file' => 198973]) === false);
check('the same id sent back: unchanged', $call('fileChanged', 198973, '198973') === false);
check('another id: changed', $call('fileChanged', 198973, '200993') === true);
check('multiple: one file dropped from the kept list: changed', $call('fileChanged', [1, 2], ['1']) === true);
check('fieldChanged on a file field uses fileChanged', $call('fieldChanged', 'UF_CRM_A7_TRADE_LICENSE_FILE', null, $emptySlot) === false);
check('fieldChanged: "" vs "N" is no change', $call('fieldChanged', 'OPENED', 'N', '') === false);
check('fieldChanged: an enum change counts', $call('fieldChanged', 'UF_CRM_A7_COMMISSION_STATUS', '2521', '2522') === true);
check('fieldChanged: the same enum sent back is no change', $call('fieldChanged', 'UF_CRM_A7_COMMISSION_STATUS', 2521, '2521') === false);

// touchedOutside on a booking-stage save as the form sends it (lead 78387: the one refused thirteen times)
$old = A7LeadGuard::loadLead(78387);
if ($old) {
    $sent = [
        'ID' => 78387,
        'TITLE' => $old['TITLE'],                      // sent back unchanged
        'STATUS_ID' => $old['STATUS_ID'],
        'UF_CRM_A7_COMMISSION_STATUS' => '2523',        // Paid
        'UF_CRM_A7_COMMISSION_VOUCHER' => 'V-TEST',
        'UF_CRM_A7_COMMISSION_DOC' => $emptySlot + ['old_file' => (int) ($old['UF_CRM_A7_COMMISSION_DOC'] ?? 0)],
        'UF_CRM_A7_TRADE_LICENSE_FILE' => $emptySlot,
        'UF_CRM_1758005814661' => $emptySlot,           // Lead Label (a file field)
    ];
    $booking = array_flip(A7LeadShare::bookingFields());
    $touched = $call('touchedOutside', 78387, $old, $sent, $booking);
    check('booking-only save of two booking fields with the form\'s empty uploads touches nothing else: ' . json_encode($touched), $touched === []);
    $touched = $call('touchedOutside', 78387, $old, $sent + ['COMMENTS' => 'changed'], $booking);
    check('a comment edit in the same save is refused as Comments: ' . json_encode($touched), $touched === ['Comments'] || (count($touched) === 1 && stripos($touched[0], 'comment') !== false));
    $moved = $sent;
    $moved['STATUS_ID'] = 'IN_PROCESS';
    $touched = $call('touchedOutside', 78387, $old, $moved, $booking);
    check('a stage move in a booking-only save is refused: ' . json_encode($touched), count($touched) === 1);
    $touched = $call('touchedOutside', 78387, $old, $sent, A7LeadGuard::sharedAllowedFields());
    check('the same save by a shared user touches nothing (the old false block): ' . json_encode($touched), $touched === []);
} else {
    say('lead 78387 not readable: form check skipped');
}

// 2. the booking-only decision for the refused pairs: permission reads by user id, no login
say('--- booking-only decisions (user, lead): stage / stock read / stock update / shared / bookingOnly');
foreach ([[2560, 78387], [2434, 79800], [2258, 78851], [2258, 74705], [2633, 78851], [2637, 73331], [2551, 79223], [2298, 78851]] as [$uid, $lead]) {
    try {
        $stage = A7LeadShare::isBookingLead($lead) ? 'Booking' : 'other';
        $read = A7LeadShare::stockRead($uid, $lead) ? 'read' : 'no-read';
        $upd = A7LeadShare::stockUpdate($uid, $lead) ? 'update' : 'no-update';
        $shared = A7LeadShare::isShared($lead, $uid) ? 'shared' : '-';
        $only = A7LeadShare::bookingOnly($uid, $lead) ? 'BOOKING-ONLY' : 'not booking-only';
        $can = \CCrmLead::CheckUpdatePermission($lead, \CCrmPerms::GetUserPermissions($uid)) ? 'can-update-now' : 'cannot-update';
        say("  u$uid lead $lead: $stage / $read / $upd / $shared / $only / $can");
    } catch (\Throwable $e) {
        say("  u$uid lead $lead: ERROR " . $e->getMessage());
        $fails++;
    }
}

// 3. the guard log after the deploy
$log = (string) (A7LeadGuard::config()['log_file'] ?? '');
if ($log !== '' && is_readable($log)) {
    $lines = file($log, FILE_IGNORE_NEW_LINES) ?: [];
    $tail = array_slice($lines, -8);
    say('--- guard log tail');
    foreach ($tail as $l) {
        say('  ' . $l);
    }
    $recentErrors = array_filter(array_slice($lines, -200), static fn($l) => str_contains($l, 'error') && str_contains($l, date('Y-m-d')));
    say('error lines today in the last 200: ' . count($recentErrors));
}
say($fails === 0 ? 'ALL_OK' : "FAILS=$fails");
