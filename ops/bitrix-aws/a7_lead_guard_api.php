<?php
/**
 * A7 Lead Guard — small JSON API for the UI script.
 * Deployed to: /home/bitrix/www/bitrix/tools/a7_lead_guard_api.php
 *
 * Actions (GET, authorised portal user only):
 *   ?action=me                 -> { isAdmin, userId, canDelete }
 *   ?action=info&id=123        -> lead share info (needs READ permission on that lead)
 *   ?action=batch&ids=1,2,3    -> { "1": {shared, names}, ... } for list / kanban tags (max 150 ids)
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_SECURITY_SHOW_MESSAGE', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function a7lg_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    die();
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7lg_json(['ok' => false, 'error' => 'Unauthorized'], 401);
}
if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7lg_json(['ok' => false, 'error' => 'crm module missing'], 500);
}
if (!class_exists('A7LeadGuard')) {
    $inc = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_lead_guard.php';
    if (is_readable($inc)) {
        require_once $inc;
    }
}
if (!class_exists('A7LeadGuard')) {
    a7lg_json(['ok' => false, 'error' => 'guard not installed'], 500);
}

$uid = (int) $USER->GetID();
$isAdmin = (bool) $USER->IsAdmin() || A7LeadGuard::isAdminUser($uid);
$canDelete = A7LeadGuard::mayDelete($uid);
$action = (string) ($_GET['action'] ?? 'me');

function a7lg_names(array $ids): array
{
    $out = [];
    foreach ($ids as $id) {
        $id = (int) $id;
        if ($id > 0) {
            $out[] = ['id' => $id, 'name' => A7LeadGuard::userName($id)];
        }
    }
    return $out;
}

if ($action === 'me') {
    a7lg_json([
        'ok' => true,
        'userId' => $uid,
        'isAdmin' => $isAdmin,
        'canDelete' => $canDelete,
        'version' => A7LeadGuard::VERSION,
    ]);
}

if ($action === 'info') {
    $id = (int) ($_GET['id'] ?? 0);
    if ($id <= 0) {
        a7lg_json(['ok' => false, 'error' => 'id required'], 400);
    }
    if (!\CCrmLead::CheckReadPermission($id)) {
        a7lg_json(['ok' => false, 'error' => 'Access denied'], 403);
    }
    $lead = A7LeadGuard::loadLead($id);
    if (!$lead) {
        a7lg_json(['ok' => false, 'error' => 'not found'], 404);
    }
    // "Shared" = shared through the guard after go-live (a7_lead_share). Historical
    // observers are not shown as shares and cost no extra queries.
    $observers = A7LeadGuard::perms() ? A7LeadShare::usersOf($id) : [];
    $responsible = (int) ($lead['ASSIGNED_BY_ID'] ?? 0);
    $canEdit = \CCrmLead::CheckUpdatePermission($id);
    $isObserver = in_array($uid, $observers, true);
    $sharedWrite = $isObserver && !$isAdmin && $responsible !== $uid;
    // The booking grant (guard 1.5.0): this user may update the lead only because it is on the Booking stage and they
    // can open it — the page then locks everything but the booking fields, as the server does.
    $bookingOnly = !$sharedWrite && !$isAdmin && $responsible !== $uid && A7LeadGuard::perms() && A7LeadShare::bookingOnly($uid, $id);
    a7lg_json([
        'sharedWrite' => $sharedWrite,
        'allowedFields' => $sharedWrite ? array_keys(A7LeadGuard::sharedAllowedFields()) : null,
        'bookingOnly' => $bookingOnly,
        'bookingFields' => $bookingOnly ? A7LeadShare::bookingFields() : null,
        'ok' => true,
        'id' => $id,
        'title' => (string) ($lead['TITLE'] ?? ''),
        'responsible' => ['id' => $responsible, 'name' => A7LeadGuard::userName($responsible)],
        'observers' => a7lg_names($observers),
        'shared' => count($observers) > 0,
        'isObserver' => in_array($uid, $observers, true),
        'isResponsible' => $responsible === $uid,
        'isAdmin' => $isAdmin,
        'canEdit' => (bool) $canEdit,
        'canDelete' => $canDelete && (bool) \CCrmLead::CheckDeletePermission($id),
    ]);
}

if ($action === 'pending') {
    // Shares to me that I have not dismissed yet (drives the sticky popup on CRM pages).
    $items = [];
    if (A7LeadGuard::perms()) {
        $since = (string) (A7LeadGuard::config()['popup_since'] ?? '');
        foreach (A7LeadShare::pendingOf($uid, $since) as $p) {
            $lead = A7LeadGuard::loadLead($p['lead']);
            if (!$lead) {
                A7LeadShare::ack($p['lead'], $uid); // lead gone: nothing to show
                continue;
            }
            $byName = A7LeadGuard::userName($p['by']);
            $initials = '';
            foreach (preg_split('~\s+~', trim($byName)) as $w) {
                if ($w !== '' && mb_strlen($initials) < 2) {
                    $initials .= mb_strtoupper(mb_substr($w, 0, 1));
                }
            }
            $items[] = [
                'lead' => $p['lead'],
                'title' => (string) ($lead['TITLE'] ?? ('Lead #' . $p['lead'])),
                'by' => $byName,
                'initials' => $initials !== '' ? $initials : '•',
                'at' => $p['at'],
                'responsible' => A7LeadGuard::userName((int) ($lead['ASSIGNED_BY_ID'] ?? 0)),
                'url' => '/crm/lead/details/' . $p['lead'] . '/',
            ];
        }
    }
    a7lg_json(['ok' => true, 'items' => $items]);
}

if ($action === 'ack') {
    // POST lead=<id>&sessid=<bitrix sessid>: dismiss my popup for that lead.
    if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !check_bitrix_sessid()) {
        a7lg_json(['ok' => false, 'error' => 'Invalid session'], 403);
    }
    $leadId = (int) ($_POST['lead'] ?? 0);
    if ($leadId > 0 && A7LeadGuard::perms()) {
        A7LeadShare::ack($leadId, $uid);
        // also clear the matching IM confirm notification, if still there
        try {
            if (\Bitrix\Main\Loader::includeModule('im')) {
                \CIMNotify::DeleteByTag('A7_LEAD_SHARE|' . $leadId . '|' . $uid, $uid);
            }
        } catch (\Throwable $e) {
            // best effort
        }
    }
    a7lg_json(['ok' => true]);
}

if ($action === 'batch') {
    $raw = (string) ($_GET['ids'] ?? '');
    $ids = array_values(array_unique(array_filter(array_map('intval', explode(',', $raw)))));
    $ids = array_slice($ids, 0, 150);
    $out = [];
    // One query for all ids; only guard shares count. Read permission is checked only
    // for the few leads that actually are shared (the list already filtered the rest).
    $shared = A7LeadGuard::perms() ? A7LeadShare::sharedAmong($ids) : [];
    foreach ($shared as $id => $obs) {
        try {
            if (!\CCrmLead::CheckReadPermission((int) $id)) {
                continue;
            }
            $out[(string) $id] = [
                'shared' => true,
                'names' => array_map(static fn($o) => $o['name'], a7lg_names($obs)),
                'mine' => in_array($uid, $obs, true),
            ];
        } catch (\Throwable $e) {
            // skip this id
        }
    }
    a7lg_json(['ok' => true, 'items' => $out]);
}

a7lg_json(['ok' => false, 'error' => 'Unknown action'], 400);
