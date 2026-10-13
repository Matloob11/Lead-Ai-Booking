<?php
/**
 * A7 Lead Guard — server-side enforcement for Bitrix24 CRM Leads.
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_lead_guard.php
 * Loaded from: /home/bitrix/www/bitrix/php_interface/init.php  (see deploy_lead_guard.php)
 *
 * What it enforces (all layers are independent; any one of them is enough):
 *
 *  DELETE LOCK
 *   - crm:OnBeforeCrmLeadDelete      -> non-admins cannot delete a lead (any code path).
 *   - crm:OnBeforeActivityDelete     -> non-admins cannot delete an activity on a lead.
 *   - main:OnBeforeProlog / OnProlog -> AJAX gate: delete actions for timeline comments,
 *                                       activities and items on leads are refused for
 *                                       non-admins before Bitrix even sees them.
 *   - lock_lead_delete_roles.php     -> strips LEAD DELETE from every CRM role (UI hides
 *                                       the Delete button, REST refuses too).
 *
 *  EDIT HISTORY
 *   - crm:OnBeforeCrmLeadUpdate      -> snapshot old values.
 *   - crm:OnAfterCrmLeadUpdate       -> timeline note "Edited by X: Field: old -> new".
 *   - ORM Timeline::OnBeforeUpdate   -> a comment edit stays ONE entry: the same comment
 *                                       gets "✏️ Edited by X · date / Previous: …" appended.
 *     The lead notes are timeline comments tagged SETTINGS.A7_GUARD, and the gate refuses
 *     any update/delete of a tagged note for everybody except admins.
 *
 *  SHARING (= Bitrix Observers on the lead)
 *   - crm:OnAfterCrmLeadUpdate       -> new observers get an IM notification, so do the
 *                                       responsible person and the admins. Removal too.
 *   - crm:OnBeforeCrmLeadUpdate      -> an observer who is neither responsible nor admin
 *                                       cannot change the locked (left-side) fields.
 *
 *  UI
 *   - main:OnProlog                  -> injects /bitrix/js/a7_lead_guard.js on /crm/lead/
 *                                       pages: "SHARED LEAD" badge, shared-with names next
 *                                       to Responsible, "Shared" tag in list/kanban, and
 *                                       hides Delete controls for non-admins.
 *
 * Everything is wrapped in try/catch: the guard must never break a page or a save.
 */

use Bitrix\Main\EventManager;
use Bitrix\Main\Loader;

if (defined('A7_LEAD_GUARD_LOADED')) {
    return;
}
define('A7_LEAD_GUARD_LOADED', true);

// The shared-lead write permission lives in a7_lead_guard_perms.php. It extends CRM
// kernel classes, so it is loaded lazily (A7LeadGuard::perms()) once the crm module is
// available, and by the service constructor in .settings_extra.php — never at init time.

final class A7LeadGuard
{
    public const VERSION = '1.4.2';
    public const LEAD = 1;                 // \CCrmOwnerType::Lead
    public const NOTE_TAG = 'A7_GUARD';    // SETTINGS key on our timeline notes
    public const JS_PATH = '/bitrix/js/a7_lead_guard.js';

    /** @var array|null */
    private static $cfg = null;
    /** @var array leadId => diff rows captured before update */
    private static $pendingDiff = [];
    /** @var array leadId => observer ids before update */
    private static $pendingObservers = [];
    /** @var bool */
    private static $gateDone = false;
    /** @var bool true while the request is a timeline comment add/update (no lead "Edited" note then) */
    private static $inCommentAction = false;

    /* ------------------------------------------------------------------ */
    /* Bootstrap                                                            */
    /* ------------------------------------------------------------------ */

    public static function register(): void
    {
        $em = EventManager::getInstance();
        $em->addEventHandler('main', 'OnBeforeProlog', [__CLASS__, 'onBeforeProlog']);
        $em->addEventHandler('main', 'OnProlog', [__CLASS__, 'onProlog']);
        $em->addEventHandler('crm', 'OnBeforeCrmLeadDelete', [__CLASS__, 'onBeforeLeadDelete']);
        $em->addEventHandler('crm', 'OnBeforeCrmLeadUpdate', [__CLASS__, 'onBeforeLeadUpdate']);
        $em->addEventHandler('crm', 'OnAfterCrmLeadUpdate', [__CLASS__, 'onAfterLeadUpdate']);
        $em->addEventHandler('crm', 'OnBeforeActivityDelete', [__CLASS__, 'onBeforeActivityDelete']);
        // Second layer for Engine controllers (main:<ControllerClass>::onBeforeAction).
        foreach (self::ENGINE_CONTROLLERS as $cls) {
            $em->addEventHandler('main', $cls . '::onBeforeAction', [__CLASS__, 'onEngineBeforeAction']);
        }
        // Timeline comment edits: keep ONE entry, append an "edited" trail inside it (ORM event).
        $em->addEventHandler('crm', '\Bitrix\Crm\Timeline\Entity\Timeline::OnBeforeUpdate', [__CLASS__, 'onTimelineBeforeUpdate']);
        // "Got it" on the sticky share notification -> mark the share acknowledged.
        $em->addEventHandler('im', 'OnBeforeConfirmNotify', [__CLASS__, 'onConfirmNotify']);
        // Fallback injection of the page script right before </body> (any template).
        $em->addEventHandler('main', 'OnEndBufferContent', [__CLASS__, 'onEndBufferContent']);
    }

    /** main:OnEndBufferContent(&$content): make sure every HTML page carries the script. */
    public static function onEndBufferContent(&$content): void
    {
        try {
            if (PHP_SAPI === 'cli' || !is_string($content) || $content === '' || self::currentUserId() <= 0) {
                return;
            }
            if (!self::wantsJs()) {
                return;
            }
            $pos = strripos($content, '</body>');
            if ($pos === false || stripos($content, 'a7_lead_guard.js') !== false) {
                return; // not an HTML page, or already injected via the head
            }
            $file = $_SERVER['DOCUMENT_ROOT'] . self::JS_PATH;
            if (!is_file($file)) {
                return;
            }
            $tag = '<script src="' . self::JS_PATH . '?v=' . filemtime($file) . '"></script>';
            $content = substr($content, 0, $pos) . $tag . "\n" . substr($content, $pos);
        } catch (\Throwable $e) {
            self::log('onEndBufferContent error: ' . $e->getMessage());
        }
    }

    /** Should this request get the page script? (portal pages only) */
    private static function wantsJs(): bool
    {
        $uri = (string) ($_SERVER['REQUEST_URI'] ?? '');
        foreach (['/bitrix/', '/rest/', '/pub/', '/mobile/', '/desktop_app/', '/online/', '/upload/'] as $skip) {
            if (str_starts_with($uri, $skip)) {
                return false;
            }
        }
        if (defined('ADMIN_SECTION') && ADMIN_SECTION === true) {
            return false;
        }
        return true;
    }

    /* ------------------------------------------------------------------ */
    /* COMMENT EDIT TRAIL — same comment, no extra entry                    */
    /* ------------------------------------------------------------------ */

    public const EDIT_SEP = "\n──────────\n✏️ Edited by ";
    public const EDIT_MAX_VERSIONS = 5;
    public const EDIT_MAX_CHARS = 600;

    /** TYPE_ID of a timeline comment on this kernel (7 on Bitrix 26; read from the constant when present). */
    public static function commentTypeId(): int
    {
        if (class_exists('\Bitrix\Crm\Timeline\TimelineType') && defined('\Bitrix\Crm\Timeline\TimelineType::COMMENT')) {
            return (int) \Bitrix\Crm\Timeline\TimelineType::COMMENT;
        }
        return 7;
    }

    /** Strip our own trail from a comment text (the editor sends it back as part of the text). */
    public static function stripEditTrail(string $text): string
    {
        $pos = mb_strpos($text, self::EDIT_SEP);
        if ($pos === false) {
            // tolerate CRLF / trimmed variants
            $pos = mb_strpos($text, trim(self::EDIT_SEP));
            if ($pos === false) {
                return rtrim($text);
            }
        }
        return rtrim(mb_substr($text, 0, $pos));
    }

    /**
     * Build the new comment text + settings for an edit.
     * $history = list of previous versions [['by'=>name,'at'=>'d.m.Y H:i','text'=>...], ...] newest first.
     */
    public static function buildEditedComment(string $oldText, string $newText, array $history, string $editorName, string $when): array
    {
        $oldPure = self::stripEditTrail($oldText);
        $newPure = self::stripEditTrail($newText);
        if (trim($oldPure) === trim($newPure)) {
            return ['changed' => false, 'text' => $newText, 'history' => $history];
        }
        array_unshift($history, [
            'by' => $editorName,
            'at' => $when,
            'text' => mb_substr($oldPure, 0, self::EDIT_MAX_CHARS),
        ]);
        $history = array_slice($history, 0, self::EDIT_MAX_VERSIONS);
        $trail = '';
        foreach ($history as $i => $h) {
            $trail .= ($i === 0 ? self::EDIT_SEP : "\n✏️ Edited by ") . $h['by'] . ' · ' . $h['at']
                . "\nPrevious: [QUOTE]" . $h['text'] . "[/QUOTE]";
        }
        return ['changed' => true, 'text' => $newPure . "\n" . $trail, 'history' => $history];
    }

    /** crm:\Bitrix\Crm\Timeline\Entity\Timeline::OnBeforeUpdate */
    public static function onTimelineBeforeUpdate(\Bitrix\Main\ORM\Event $event)
    {
        try {
            $fields = (array) $event->getParameter('fields');
            if (!array_key_exists('COMMENT', $fields)) {
                return null;
            }
            $idParam = $event->getParameter('id');
            $id = is_array($idParam) ? (int) ($idParam['ID'] ?? 0) : (int) $idParam;
            if ($id <= 0) {
                return null;
            }
            $row = \Bitrix\Crm\Timeline\Entity\TimelineTable::getById($id)->fetch();
            if (!$row) {
                return null;
            }
            // Only timeline comments (TimelineType::COMMENT) bound to a protected entity.
            if ((int) ($row['TYPE_ID'] ?? 0) !== self::commentTypeId()) {
                return null;
            }
            $protected = false;
            $bq = \Bitrix\Crm\Timeline\Entity\TimelineBindingTable::getList(['filter' => ['=OWNER_ID' => $id]]);
            $hasBinding = false;
            while ($b = $bq->fetch()) {
                $hasBinding = true;
                if (self::isProtectedOwner((int) $b['ENTITY_TYPE_ID'])) {
                    $protected = true;
                }
            }
            if ($hasBinding && !$protected) {
                return null;
            }
            $settings = $row['SETTINGS'] ?? [];
            if (is_string($settings)) {
                $settings = @unserialize($settings, ['allowed_classes' => false]) ?: [];
            }
            if (!is_array($settings)) {
                $settings = [];
            }
            $history = isset($settings['A7_EDITS']) && is_array($settings['A7_EDITS']) ? $settings['A7_EDITS'] : [];
            $uid = self::currentUserId();
            $oldText = \Bitrix\Main\Text\Emoji::decode((string) ($row['COMMENT'] ?? ''));
            $newText = \Bitrix\Main\Text\Emoji::decode((string) $fields['COMMENT']);
            $built = self::buildEditedComment($oldText, $newText, $history, self::userName($uid), date('d.m.Y H:i'));
            if (!$built['changed']) {
                return null;
            }
            $settings['A7_EDITS'] = $built['history'];
            $modify = ['COMMENT' => \Bitrix\Main\Text\Emoji::encode($built['text'])];
            if (!array_key_exists('SETTINGS', $fields)) {
                $modify['SETTINGS'] = $settings;
            } else {
                $s = is_array($fields['SETTINGS']) ? $fields['SETTINGS'] : [];
                $s['A7_EDITS'] = $built['history'];
                $modify['SETTINGS'] = $s;
            }
            self::log("COMMENT EDIT trail comment=$id user=$uid versions=" . count($built['history']));
            $result = new \Bitrix\Main\ORM\EventResult();
            $result->modifyFields($modify);
            return $result;
        } catch (\Throwable $e) {
            self::log('onTimelineBeforeUpdate error: ' . $e->getMessage());
            return null;
        }
    }

    /** Engine controllers whose delete actions are guarded (class names without leading backslash). */
    public const ENGINE_CONTROLLERS = [
        'Bitrix\Crm\Controller\Timeline\Comment',
        'Bitrix\Crm\Controller\Timeline\Activity',
        'Bitrix\Crm\Controller\Timeline\Document',
        'Bitrix\Crm\Controller\Activity\ToDo',
        'Bitrix\Crm\Controller\Item',
    ];

    /** main:<Controller>::onBeforeAction — refuse delete actions on protected items for non-admins. */
    public static function onEngineBeforeAction(\Bitrix\Main\Event $event)
    {
        try {
            $action = $event->getParameter('action');
            $name = is_object($action) && method_exists($action, 'getName') ? strtolower((string) $action->getName()) : '';
            if ($name === '' || !preg_match('~^(delete|remove)~', $name) || $name === 'deletetag') {
                return null;
            }
            $uid = self::currentUserId();
            if ($uid <= 0 || self::mayDelete($uid)) {
                return null;
            }
            $ownerTypeId = self::ownerTypeFromRequest($_REQUEST);
            $protected = $ownerTypeId === null
                ? (bool) self::config()['block_when_owner_unknown']
                : self::isProtectedOwner($ownerTypeId);
            if (!$protected) {
                return null;
            }
            $controller = $event->getParameter('controller');
            self::log('BLOCK engine action ' . (is_object($controller) ? get_class($controller) : '?') . "::$name user=$uid owner=" . var_export($ownerTypeId, true));
            return new \Bitrix\Main\EventResult(
                \Bitrix\Main\EventResult::ERROR,
                ['errors' => [new \Bitrix\Main\Error('Deleting is not allowed on leads. Only an administrator can delete.', 'A7_DELETE_LOCKED')]],
                'crm'
            );
        } catch (\Throwable $e) {
            self::log('onEngineBeforeAction error: ' . $e->getMessage());
            return null;
        }
    }

    /** Load the shared-lead permission classes (needs the crm module). */
    public static function perms(): bool
    {
        if (class_exists('A7LeadShare', false)) {
            return true;
        }
        try {
            if (!Loader::includeModule('crm')) {
                return false;
            }
            $f = __DIR__ . '/a7_lead_guard_perms.php';
            if (is_file($f)) {
                require_once $f;
            }
        } catch (\Throwable $e) {
            self::log('perms load error: ' . $e->getMessage());
        }
        return class_exists('A7LeadShare', false);
    }

    public static function config(): array
    {
        if (self::$cfg !== null) {
            return self::$cfg;
        }
        $defaults = [
            'delete_allow_user_ids' => [],
            'notify_admin_ids' => [],
            'protect_owner_type_ids' => [self::LEAD],
            'block_when_owner_unknown' => true,
            'history_notes' => true,
            'history_ignore_fields' => ['ID', 'DATE_MODIFY', 'MODIFY_BY_ID', 'TIMESTAMP_X', 'SEARCH_CONTENT', 'FM', 'OBSERVER_IDS'],
            'observer_locked_fields' => ['TITLE', 'NAME', 'LAST_NAME', 'STATUS_ID', 'ASSIGNED_BY_ID', 'SOURCE_ID', 'OPPORTUNITY', 'FM'],
            'log_file' => '',
        ];
        $path = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_lead_guard.config.php';
        $loaded = is_readable($path) ? include $path : null;
        self::$cfg = array_merge($defaults, is_array($loaded) ? $loaded : []);
        return self::$cfg;
    }

    public static function log(string $msg): void
    {
        $file = (string) (self::config()['log_file'] ?? '');
        if ($file === '') {
            return;
        }
        @file_put_contents($file, date('Y-m-d H:i:s') . ' ' . $msg . "\n", FILE_APPEND);
    }

    /* ------------------------------------------------------------------ */
    /* Who is the current user                                              */
    /* ------------------------------------------------------------------ */

    public static function currentUserId(): int
    {
        global $USER;
        return (is_object($USER) && $USER->IsAuthorized()) ? (int) $USER->GetID() : 0;
    }

    /** Portal admin (group 1) or explicitly allowed to delete. */
    public static function mayDelete(?int $userId = null): bool
    {
        global $USER;
        $userId = $userId ?? self::currentUserId();
        if ($userId <= 0) {
            // CLI / agents / system context: never block Bitrix internals.
            return true;
        }
        if (in_array($userId, array_map('intval', self::config()['delete_allow_user_ids']), true)) {
            return true;
        }
        if (is_object($USER) && (int) $USER->GetID() === $userId && $USER->IsAdmin()) {
            return true;
        }
        return self::isAdminUser($userId);
    }

    public static function isAdminUser(int $userId): bool
    {
        if ($userId <= 0) {
            return false;
        }
        static $cache = [];
        if (!isset($cache[$userId])) {
            $groups = array_map('intval', (array) \CUser::GetUserGroup($userId));
            $cache[$userId] = in_array(1, $groups, true);
        }
        return $cache[$userId];
    }

    /* ------------------------------------------------------------------ */
    /* DELETE LOCK — legacy CRM events                                      */
    /* ------------------------------------------------------------------ */

    /** crm:OnBeforeCrmLeadDelete($ID). Return false to cancel. */
    public static function onBeforeLeadDelete($ID)
    {
        global $APPLICATION;
        try {
            if (self::mayDelete()) {
                return true;
            }
            $uid = self::currentUserId();
            self::log("BLOCK lead delete lead=$ID user=$uid");
            $APPLICATION->ThrowException('Leads cannot be deleted. Only an administrator can delete a lead.', 'A7_DELETE_LOCKED');
            return false;
        } catch (\Throwable $e) {
            self::log('onBeforeLeadDelete error: ' . $e->getMessage());
            return true;
        }
    }

    /** crm:OnBeforeActivityDelete($ID). Return false to cancel. */
    public static function onBeforeActivityDelete($ID)
    {
        global $APPLICATION;
        try {
            if (self::mayDelete()) {
                return true;
            }
            $id = (int) $ID;
            if ($id > 0 && class_exists('\CCrmActivity')) {
                $act = \CCrmActivity::GetByID($id, false);
                if ($act && !self::isProtectedOwner((int) ($act['OWNER_TYPE_ID'] ?? 0))) {
                    return true;
                }
            }
            self::log("BLOCK activity delete act=$id user=" . self::currentUserId());
            $APPLICATION->ThrowException('Items on a lead cannot be deleted. Only an administrator can delete.', 'A7_DELETE_LOCKED');
            return false;
        } catch (\Throwable $e) {
            self::log('onBeforeActivityDelete error: ' . $e->getMessage());
            return true;
        }
    }

    private static function isProtectedOwner(int $ownerTypeId): bool
    {
        return in_array($ownerTypeId, array_map('intval', self::config()['protect_owner_type_ids']), true);
    }

    /* ------------------------------------------------------------------ */
    /* DELETE LOCK + COMMENT HISTORY — AJAX gate                            */
    /* ------------------------------------------------------------------ */

    public static function onBeforeProlog(): void
    {
        self::gate();
    }

    public static function onProlog(): void
    {
        self::gate();
        self::injectJs();
    }

    /**
     * Inspect the current HTTP request. If it is a delete of a protected item by a
     * non-admin, answer with a JSON error and stop. If it is a comment edit on a
     * protected item, record the previous text first, then let it through.
     */
    private static function gate(): void
    {
        if (self::$gateDone || PHP_SAPI === 'cli') {
            return;
        }
        try {
            $uid = self::currentUserId();
            if ($uid <= 0) {
                return; // not authorised yet; a later hook (OnProlog) or the CRM events will handle it
            }
            self::$gateDone = true;

            $script = (string) ($_SERVER['SCRIPT_NAME'] ?? '');
            $uri = (string) ($_SERVER['REQUEST_URI'] ?? '');
            $req = $_REQUEST;

            $isEngine = str_contains($script, '/bitrix/services/main/ajax.php') || str_contains($uri, '/bitrix/services/main/ajax.php');
            $isCrmComponentAjax = (bool) preg_match('~/bitrix/components/bitrix/crm\.[a-z0-9_.]+/(ajax|list\.ajax|ajax_[a-z_]+)\.php~i', $script . ' ' . $uri);
            if (!$isEngine && !$isCrmComponentAjax) {
                return;
            }

            $action = strtolower(trim((string) ($req['action'] ?? $req['ACTION'] ?? '')));
            if ($action === '') {
                return;
            }
            $ownerTypeId = self::ownerTypeFromRequest($req);
            $protected = $ownerTypeId === null
                ? (bool) self::config()['block_when_owner_unknown']
                : self::isProtectedOwner($ownerTypeId);

            // --- our own history notes: nobody but admins may touch them ---
            if ($isEngine && preg_match('~^crm\.(api\.)?timeline\.comment\.(update|delete)$~', $action)) {
                $commentId = (int) ($req['id'] ?? $req['ID'] ?? 0);
                if ($commentId > 0 && self::isGuardNote($commentId) && !self::mayDelete($uid)) {
                    self::refuse('This history note is protected and cannot be changed.');
                }
            }

            // --- deletes ---
            $isDelete = false;
            if ($isEngine) {
                $isDelete = (bool) preg_match('~^crm\.(api\.)?(timeline|activity|item|entity|lead|todo)(\.[a-z0-9_]+)*\.(delete|remove)$~', $action)
                    || (bool) preg_match('~^crm\.(api\.)?timeline\.comment\.delete$~', $action);
            } else {
                $isDelete = in_array($action, ['delete', 'delete_comment', 'delete_activity', 'deletecomment', 'remove'], true)
                    || str_starts_with($action, 'delete');
            }
            if ($isDelete && $protected && !self::mayDelete($uid)) {
                self::log("BLOCK ajax delete action=$action owner=" . var_export($ownerTypeId, true) . " user=$uid");
                self::refuse('Deleting is not allowed on leads. Only an administrator can delete.');
            }

            // Comment edits are handled in-place by onTimelineBeforeUpdate (no extra entry).
            if (preg_match('~^crm\.(api\.)?timeline\.comment\.~', $action)) {
                self::$inCommentAction = true;
            }
        } catch (\Throwable $e) {
            self::log('gate error: ' . $e->getMessage());
        }
    }

    private static function ownerTypeFromRequest(array $req): ?int
    {
        foreach (['ownerTypeId', 'OWNER_TYPE_ID', 'entityTypeId', 'ENTITY_TYPE_ID', 'owner_type_id', 'entity_type_id'] as $k) {
            if (isset($req[$k]) && $req[$k] !== '') {
                return (int) $req[$k];
            }
        }
        foreach (['ownerType', 'OWNER_TYPE', 'entityType', 'ENTITY_TYPE', 'ownerTypeName', 'entityTypeName'] as $k) {
            if (isset($req[$k]) && $req[$k] !== '' && class_exists('\CCrmOwnerType')) {
                $id = \CCrmOwnerType::ResolveID((string) $req[$k]);
                if ($id > 0) {
                    return (int) $id;
                }
            }
        }
        // Engine actions may nest params: data[ownerTypeId] / params[ownerTypeId]
        foreach (['data', 'params', 'fields'] as $bag) {
            if (isset($req[$bag]) && is_array($req[$bag])) {
                $nested = self::ownerTypeFromRequest($req[$bag]);
                if ($nested !== null) {
                    return $nested;
                }
            }
        }
        // Engine JSON body
        static $json = null;
        if ($json === null) {
            $json = [];
            $raw = file_get_contents('php://input');
            if (is_string($raw) && $raw !== '' && ($raw[0] === '{' || $raw[0] === '[')) {
                $dec = json_decode($raw, true);
                if (is_array($dec)) {
                    $json = $dec;
                }
            }
        }
        if ($json && $json !== $req) {
            $nested = self::ownerTypeFromRequest($json);
            if ($nested !== null) {
                return $nested;
            }
        }
        return null;
    }

    private static function refuse(string $message): void
    {
        global $APPLICATION;
        if (is_object($APPLICATION)) {
            $APPLICATION->RestartBuffer();
        }
        if (!headers_sent()) {
            header('Content-Type: application/json; charset=utf-8');
            http_response_code(200); // Bitrix Engine expects 200 + status:error
        }
        echo json_encode([
            'status' => 'error',
            'data' => null,
            'errors' => [['message' => $message, 'code' => 'A7_DELETE_LOCKED', 'customData' => null]],
            'ERROR' => $message,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        die();
    }

    private static function isGuardNote(int $commentId): bool
    {
        if (!Loader::includeModule('crm') || !class_exists('\Bitrix\Crm\Timeline\Entity\TimelineTable')) {
            return false;
        }
        $row = \Bitrix\Crm\Timeline\Entity\TimelineTable::getById($commentId)->fetch();
        if (!$row) {
            return false;
        }
        $settings = $row['SETTINGS'] ?? [];
        if (is_string($settings)) {
            $settings = @unserialize($settings, ['allowed_classes' => false]) ?: [];
        }
        return is_array($settings) && !empty($settings[self::NOTE_TAG]);
    }

    /* ------------------------------------------------------------------ */
    /* EDIT HISTORY + SHARE — lead update events                            */
    /* ------------------------------------------------------------------ */

    /** crm:OnBeforeCrmLeadUpdate(&$arFields). Return false to cancel. */
    public static function onBeforeLeadUpdate(&$arFields)
    {
        global $APPLICATION;
        try {
            $id = (int) ($arFields['ID'] ?? 0);
            if ($id <= 0 || !is_array($arFields)) {
                return true;
            }
            $uid = self::currentUserId();
            $old = self::loadLead($id);
            if (!$old) {
                return true;
            }

            // Shared users (observers who are neither responsible nor admin) may change ONLY
            // the stage and the fields Bitrix requires on stages. Everything else on the
            // left side is locked. Unchanged values that the form sends back are fine.
            // Only for shares made through the guard (a7_lead_share) — historical observers
            // have no write access anyway, so nothing to check and no extra queries for them.
            if ($uid > 0 && !self::isAdminUser($uid) && (int) $old['ASSIGNED_BY_ID'] !== $uid
                && self::perms() && A7LeadShare::isShared($id, $uid)) {
                $observers = self::observerIds($id);
                if (in_array($uid, $observers, true)) {
                    $allowed = self::sharedAllowedFields();
                    $ignore = array_flip(array_map('strtoupper', (array) self::config()['history_ignore_fields']));
                    $touched = [];
                    foreach ($arFields as $key => $val) {
                        $f = strtoupper((string) $key);
                        if ($f === '' || $f === 'ID' || isset($ignore[$f]) || isset($allowed[$f]) || $f[0] === '~' || str_starts_with($f, 'PERMISSION')) {
                            continue;
                        }
                        if ($f === 'FM') {
                            if (self::diffMulti($id, is_array($val) ? $val : [])) {
                                $touched[] = 'Phone/Email';
                            }
                            continue;
                        }
                        if ($f === 'OBSERVER_IDS') {
                            $new = array_values(array_unique(array_map('intval', (array) $val)));
                            $cur = $observers;
                            sort($new);
                            sort($cur);
                            if ($new !== $cur) {
                                $touched[] = 'Observers';
                            }
                            continue;
                        }
                        if (array_key_exists($key, $old) && self::norm($old[$key]) !== self::norm($val)) {
                            $touched[] = self::caption($f);
                        }
                    }
                    if ($touched) {
                        self::log("BLOCK shared-user edit lead=$id user=$uid fields=" . implode(',', $touched));
                        $APPLICATION->ThrowException(
                            'This lead is shared with you. You can change the stage and its details, but not: ' . implode(', ', array_unique($touched)) . '. Only the responsible person or an administrator can edit these.',
                            'A7_SHARED_READONLY'
                        );
                        return false;
                    }
                }
            }

            if (array_key_exists('OBSERVER_IDS', $arFields)) {
                self::$pendingObservers[$id] = self::observerIds($id);
            }

            // Adding / editing a timeline comment must produce exactly one entry (the comment
            // itself), so no lead "Edited" note for side-effect field updates in that request.
            if (self::config()['history_notes'] && !self::$inCommentAction) {
                $diff = self::diffFields($old, $arFields);
                if (isset($arFields['FM']) && is_array($arFields['FM'])) {
                    $diff = array_merge($diff, self::diffMulti($id, $arFields['FM']));
                }
                if ($diff) {
                    self::$pendingDiff[$id] = $diff;
                }
            }
        } catch (\Throwable $e) {
            self::log('onBeforeLeadUpdate error: ' . $e->getMessage());
        }
        return true;
    }

    /** crm:OnAfterCrmLeadUpdate(&$arFields). */
    public static function onAfterLeadUpdate(&$arFields): void
    {
        try {
            $id = (int) ($arFields['ID'] ?? 0);
            if ($id <= 0) {
                return;
            }
            $uid = self::currentUserId();
            $editor = $uid > 0 ? $uid : (int) ($arFields['MODIFY_BY_ID'] ?? 0);

            if (isset(self::$pendingDiff[$id])) {
                $diff = self::$pendingDiff[$id];
                unset(self::$pendingDiff[$id]);
                $lines = [];
                foreach ($diff as $row) {
                    $lines[] = "• {$row[0]}: " . ($row[1] === '' ? '(empty)' : $row[1]) . " → " . ($row[2] === '' ? '(empty)' : $row[2]);
                }
                $text = "✏️ Edited by " . self::userName($editor) . ":\n" . implode("\n", $lines);
                self::addNote(self::LEAD, $id, $text, $editor, ['kind' => 'field_edit']);
            }

            if (isset(self::$pendingObservers[$id])) {
                $before = self::$pendingObservers[$id];
                unset(self::$pendingObservers[$id]);
                $after = array_values(array_unique(array_map('intval', (array) ($arFields['OBSERVER_IDS'] ?? []))));
                $added = array_values(array_diff($after, $before));
                $removed = array_values(array_diff($before, $after));
                if ($added || $removed) {
                    self::onShareChanged($id, $editor, $added, $removed);
                }
            }
        } catch (\Throwable $e) {
            self::log('onAfterLeadUpdate error: ' . $e->getMessage());
        }
    }

    private static function onShareChanged(int $leadId, int $byUserId, array $added, array $removed): void
    {
        $lead = self::loadLead($leadId);
        if (!$lead) {
            return;
        }
        $title = trim((string) ($lead['TITLE'] ?? '')) ?: ('Lead #' . $leadId);
        $link = '/crm/lead/details/' . $leadId . '/';
        $by = self::userName($byUserId);
        $responsible = (int) ($lead['ASSIGNED_BY_ID'] ?? 0);
        $tag = 'A7_LEAD_SHARE|' . $leadId;

        $addedNames = array_map([__CLASS__, 'userName'], $added);
        $removedNames = array_map([__CLASS__, 'userName'], $removed);

        // 0. share registry: gives the shared users update rights on THIS lead only
        //    (see a7_lead_guard_perms.php); removing the observer ends it.
        if (self::perms()) {
            try {
                A7LeadShare::ensureTable();
                // Row for everybody except the responsible person (admins too: the row drives
                // the on-screen popup; the extra update right is irrelevant for admins).
                foreach ($added as $u) {
                    if ($u !== $responsible) {
                        A7LeadShare::add($leadId, $u, $byUserId);
                    }
                }
                foreach ($removed as $u) {
                    A7LeadShare::remove($leadId, $u);
                }
            } catch (\Throwable $e) {
                self::log('share registry error: ' . $e->getMessage());
            }
        }

        // 1. ONLY the shared users are notified (user decision 2026-09-15). The notification
        //    is a Bitrix "confirm" notification: it stays in the notification panel with an
        //    unread badge until the person presses "Got it". In addition the CRM pages show a
        //    popup (a7_lead_guard.js, API action=pending) until dismissed; both paths set ACKED.
        foreach ($added as $to) {
            self::notify(
                $to,
                "🔗 Lead shared with you: [URL={$link}]{$title}[/URL] (#{$leadId}) by {$by}.\nYou can see all details, change the stage and its details, and add or edit your own comments. You cannot delete anything or change the other lead fields.",
                $tag . '|' . $to,
                $byUserId,
                true
            );
            // Instant on-screen popup on whatever page the person has open (Bitrix push).
            self::push($to, ['lead' => $leadId, 'title' => $title, 'by' => $by, 'url' => $link]);
        }
        foreach ($removed as $to) {
            self::notify($to, "Lead [URL={$link}]{$title}[/URL] (#{$leadId}) is no longer shared with you (by {$by}).", $tag . '|' . $to . '|off', $byUserId);
        }

        // 1b. admins: who shared which lead with whom (plain notification, user decision 2026-09-16)
        foreach (self::adminRecipients() as $to) {
            if ($to === $byUserId || in_array($to, $added, true)) {
                continue;
            }
            $msg = "🔗 Lead share: {$by} ";
            if ($added) {
                $msg .= "shared [URL={$link}]{$title}[/URL] (#{$leadId}) with " . implode(', ', $addedNames) . '. ';
            }
            if ($removed) {
                $msg .= "removed sharing of [URL={$link}]{$title}[/URL] (#{$leadId}) for " . implode(', ', $removedNames) . '. ';
            }
            $msg .= 'Responsible: ' . self::userName($responsible) . '.';
            self::notify($to, $msg, $tag . '|adm|' . $to, $byUserId);
        }

        // 2. timeline note (permanent record)
        $note = '';
        if ($added) {
            $note .= "🔗 Shared with " . implode(', ', $addedNames) . " by {$by}. Shared users see the full lead, can change the stage and add comments, cannot delete or edit other fields.";
        }
        if ($removed) {
            $note .= ($note ? "\n" : '') . "Sharing removed for " . implode(', ', $removedNames) . " by {$by}.";
        }
        self::addNote(self::LEAD, $leadId, $note, $byUserId, ['kind' => 'share', 'added' => $added, 'removed' => $removed]);
        self::log("SHARE lead=$leadId by=$byUserId added=" . json_encode($added) . " removed=" . json_encode($removed));
    }

    private static function adminRecipients(): array
    {
        $ids = array_values(array_filter(array_map('intval', (array) self::config()['notify_admin_ids'])));
        if ($ids) {
            return $ids;
        }
        $out = [];
        try {
            $rs = \CUser::GetList('ID', 'ASC', ['GROUPS_ID' => [1], 'ACTIVE' => 'Y'], ['FIELDS' => ['ID']]);
            while ($u = $rs->Fetch()) {
                $out[] = (int) $u['ID'];
            }
        } catch (\Throwable $e) {
            self::log('adminRecipients error: ' . $e->getMessage());
        }
        return $out;
    }

    /* ------------------------------------------------------------------ */
    /* Helpers: lead data, diff, formatting                                 */
    /* ------------------------------------------------------------------ */

    public static function loadLead(int $id): ?array
    {
        if (!Loader::includeModule('crm')) {
            return null;
        }
        $rs = \CCrmLead::GetListEx([], ['=ID' => $id, 'CHECK_PERMISSIONS' => 'N'], false, false, ['*', 'UF_*']);
        $row = $rs ? $rs->Fetch() : null;
        return is_array($row) ? $row : null;
    }

    /**
     * Fields a shared user may change: the stage itself + every field Bitrix marks as
     * "required on a stage" for leads (b_crm_field_attr) + config extras. Keys uppercased.
     */
    public static function sharedAllowedFields(): array
    {
        static $cache = null;
        if ($cache !== null) {
            return $cache;
        }
        $set = ['STATUS_ID' => true, 'STATUS_DESCRIPTION' => true];
        // Bitrix links the client (contact/company found by phone/e-mail) automatically on
        // every card save; a shared user saving a stage field must not be refused for it.
        foreach (['CONTACT_ID', 'CONTACT_IDS', 'CONTACT_BINDINGS', 'COMPANY_ID', 'CLIENT_DATA', 'CLIENT_INFO'] as $f) {
            $set[$f] = true;
        }
        foreach ((array) (self::config()['shared_allowed_fields'] ?? []) as $f) {
            $set[strtoupper((string) $f)] = true;
        }
        try {
            $c = \Bitrix\Main\Application::getConnection();
            $q = $c->query('SELECT DISTINCT FIELD_NAME FROM b_crm_field_attr WHERE ENTITY_TYPE_ID=' . self::LEAD);
            while ($r = $q->fetch()) {
                $f = strtoupper((string) $r['FIELD_NAME']);
                if ($f === 'OPPORTUNITY_WITH_CURRENCY') {
                    $set['OPPORTUNITY'] = true;
                    $set['CURRENCY_ID'] = true;
                    $set['IS_MANUAL_OPPORTUNITY'] = true;
                } elseif ($f !== '') {
                    $set[$f] = true;
                }
            }
        } catch (\Throwable $e) {
            self::log('sharedAllowedFields error: ' . $e->getMessage());
        }
        $cache = $set;
        return $cache;
    }

    public static function observerIds(int $leadId): array
    {
        try {
            if (class_exists('\Bitrix\Crm\Observer\ObserverManager')) {
                return array_values(array_map('intval', \Bitrix\Crm\Observer\ObserverManager::getEntityObserverIDs(self::LEAD, $leadId)));
            }
        } catch (\Throwable $e) {
            self::log('observerIds error: ' . $e->getMessage());
        }
        return [];
    }

    private static function norm($v): string
    {
        if ($v === null) {
            return '';
        }
        if (is_bool($v)) {
            return $v ? 'Y' : 'N';
        }
        if (is_array($v)) {
            $flat = [];
            foreach ($v as $x) {
                $flat[] = self::norm($x);
            }
            sort($flat);
            return implode(', ', array_filter($flat, static fn($s) => $s !== ''));
        }
        if (is_object($v)) {
            return method_exists($v, '__toString') ? trim((string) $v) : '';
        }
        $s = trim((string) $v);
        // numeric normalisation: "100.00" == "100"
        if ($s !== '' && is_numeric($s)) {
            $f = (float) $s;
            if (abs($f - round($f)) < 0.000001 && abs($f) < 1e15) {
                return (string) (int) round($f);
            }
            return rtrim(rtrim(number_format($f, 4, '.', ''), '0'), '.');
        }
        return $s;
    }

    private static function diffFields(array $old, array $new): array
    {
        $ignore = array_flip(array_map('strtoupper', (array) self::config()['history_ignore_fields']));
        $out = [];
        foreach ($new as $key => $val) {
            $k = strtoupper((string) $key);
            if (isset($ignore[$k]) || $k === '' || $k[0] === '~' || str_starts_with($k, 'PERMISSION')) {
                continue;
            }
            if (!array_key_exists($key, $old)) {
                continue; // unknown / computed field
            }
            $a = self::norm($old[$key]);
            $b = self::norm($val);
            if ($a === $b) {
                continue;
            }
            // "" , "0" and "N" are the same "nothing" for ids, sums and Y/N flags — no noise notes.
            $nothing = ['', '0', 'N'];
            if (in_array($a, $nothing, true) && in_array($b, $nothing, true)) {
                continue;
            }
            $out[] = [self::caption($k), self::pretty($k, $old[$key], $a), self::pretty($k, $val, $b)];
        }
        return $out;
    }

    /** Compare PHONE / EMAIL / WEB / IM sets. $fm = ['PHONE' => ['n0' => ['VALUE' => ..], ...], ...] */
    private static function diffMulti(int $leadId, array $fm): array
    {
        $out = [];
        try {
            $current = [];
            $rs = \CCrmFieldMulti::GetList(['ID' => 'asc'], ['ENTITY_ID' => 'LEAD', 'ELEMENT_ID' => $leadId]);
            while ($r = $rs->Fetch()) {
                $current[strtoupper($r['TYPE_ID'])][] = trim((string) $r['VALUE']);
            }
            foreach ($fm as $type => $items) {
                $type = strtoupper((string) $type);
                $newVals = [];
                foreach ((array) $items as $it) {
                    $v = is_array($it) ? trim((string) ($it['VALUE'] ?? '')) : trim((string) $it);
                    if ($v !== '') {
                        $newVals[] = $v;
                    }
                }
                $oldVals = array_values(array_filter($current[$type] ?? []));
                sort($newVals);
                sort($oldVals);
                if ($newVals !== $oldVals) {
                    $out[] = [ucfirst(strtolower($type)), implode(', ', $oldVals), implode(', ', $newVals)];
                }
            }
        } catch (\Throwable $e) {
            self::log('diffMulti error: ' . $e->getMessage());
        }
        return $out;
    }

    private static function caption(string $field): string
    {
        try {
            if (str_starts_with($field, 'UF_')) {
                global $USER_FIELD_MANAGER;
                $ufs = $USER_FIELD_MANAGER->GetUserFields('CRM_LEAD', 0, LANGUAGE_ID);
                $label = $ufs[$field]['EDIT_FORM_LABEL'] ?? $ufs[$field]['LIST_COLUMN_LABEL'] ?? '';
                if ($label !== '') {
                    return $label;
                }
            } elseif (class_exists('\CCrmLead')) {
                $c = \CCrmLead::GetFieldCaption($field);
                if (is_string($c) && $c !== '') {
                    return $c;
                }
            }
        } catch (\Throwable $e) {
            // fall through
        }
        return ucwords(strtolower(str_replace('_', ' ', $field)));
    }

    private static function pretty(string $field, $raw, string $norm): string
    {
        try {
            switch ($field) {
                case 'STATUS_ID':
                    $list = \CCrmStatus::GetStatusList('STATUS');
                    return $list[$norm] ?? $norm;
                case 'SOURCE_ID':
                    $list = \CCrmStatus::GetStatusList('SOURCE');
                    return $list[$norm] ?? $norm;
                case 'ASSIGNED_BY_ID':
                case 'CREATED_BY_ID':
                case 'MODIFY_BY_ID':
                    return $norm === '' ? '' : self::userName((int) $norm);
                case 'CONTACT_ID':
                    if ($norm !== '' && class_exists('\CCrmContact')) {
                        $c = \CCrmContact::GetByID((int) $norm, false);
                        if ($c) {
                            return trim(($c['NAME'] ?? '') . ' ' . ($c['LAST_NAME'] ?? '')) ?: $norm;
                        }
                    }
                    return $norm;
                case 'COMPANY_ID':
                    if ($norm !== '' && class_exists('\CCrmCompany')) {
                        $c = \CCrmCompany::GetByID((int) $norm, false);
                        if ($c) {
                            return (string) ($c['TITLE'] ?? $norm);
                        }
                    }
                    return $norm;
                case 'OPENED':
                    return $norm === 'Y' ? 'Available to everyone' : 'Not available to everyone';
            }
            if (str_starts_with($field, 'UF_') && $norm !== '' && ctype_digit(str_replace(', ', '', $norm))) {
                // enumeration user field: map ids -> labels
                global $USER_FIELD_MANAGER;
                $ufs = $USER_FIELD_MANAGER->GetUserFields('CRM_LEAD', 0, LANGUAGE_ID);
                if (($ufs[$field]['USER_TYPE_ID'] ?? '') === 'enumeration') {
                    $labels = [];
                    $rs = \CUserFieldEnum::GetList([], ['USER_FIELD_ID' => $ufs[$field]['ID']]);
                    while ($e = $rs->Fetch()) {
                        $labels[(string) $e['ID']] = $e['VALUE'];
                    }
                    $parts = array_map('trim', explode(',', $norm));
                    return implode(', ', array_map(static fn($p) => $labels[$p] ?? $p, $parts));
                }
                if (($ufs[$field]['USER_TYPE_ID'] ?? '') === 'employee') {
                    $parts = array_map('trim', explode(',', $norm));
                    return implode(', ', array_map(static fn($p) => self::userName((int) $p), $parts));
                }
            }
        } catch (\Throwable $e) {
            // fall through
        }
        return mb_strlen($norm) > 300 ? mb_substr($norm, 0, 300) . '…' : $norm;
    }

    public static function userName(int $userId): string
    {
        if ($userId <= 0) {
            return 'System';
        }
        static $cache = [];
        if (!isset($cache[$userId])) {
            $u = \CUser::GetByID($userId)->Fetch();
            $name = $u ? trim(($u['NAME'] ?? '') . ' ' . ($u['LAST_NAME'] ?? '')) : '';
            if ($name === '' && $u) {
                $name = (string) ($u['LOGIN'] ?? '');
            }
            $cache[$userId] = $name !== '' ? $name : ('User #' . $userId);
        }
        return $cache[$userId];
    }

    /* ------------------------------------------------------------------ */
    /* Timeline note + IM notification                                      */
    /* ------------------------------------------------------------------ */

    public static function addNote(int $ownerTypeId, int $ownerId, string $text, int $authorId, array $meta = []): ?int
    {
        if (trim($text) === '' || !Loader::includeModule('crm') || !class_exists('\Bitrix\Crm\Timeline\CommentEntry')) {
            return null;
        }
        try {
            // De-duplicate: the same note for the same item within 2 minutes is written once.
            $dupe = \Bitrix\Crm\Timeline\Entity\TimelineTable::getList([
                'select' => ['ID', 'COMMENT', 'CREATED'],
                'filter' => ['=TYPE_ID' => self::commentTypeId(), '=BINDINGS.ENTITY_TYPE_ID' => $ownerTypeId, '=BINDINGS.ENTITY_ID' => $ownerId],
                'order' => ['ID' => 'DESC'],
                'limit' => 3,
            ]);
            while ($d = $dupe->fetch()) {
                $created = $d['CREATED'] ?? null;
                $age = ($created && is_object($created) && method_exists($created, 'getTimestamp')) ? time() - $created->getTimestamp() : 9999;
                if ($age < 120 && trim(\Bitrix\Main\Text\Emoji::decode((string) $d['COMMENT'])) === trim($text)) {
                    return (int) $d['ID'];
                }
            }
        } catch (\Throwable $e) {
            // duplicate check is best effort
        }
        try {
            if ($authorId <= 0) {
                $authorId = 1;
            }
            $settings = [self::NOTE_TAG => array_merge(['v' => self::VERSION], $meta)];
            $noteId = \Bitrix\Crm\Timeline\CommentEntry::create([
                'TEXT' => $text,
                'AUTHOR_ID' => $authorId,
                'SETTINGS' => $settings,
                'BINDINGS' => [['ENTITY_TYPE_ID' => $ownerTypeId, 'ENTITY_ID' => $ownerId]],
            ]);
            $noteId = (int) $noteId;
            if ($noteId > 0) {
                // Push to open cards (best effort; a reload shows it anyway).
                try {
                    if (class_exists('\Bitrix\Crm\Timeline\CommentController')) {
                        \Bitrix\Crm\Timeline\CommentController::getInstance()->onCreate($noteId, [
                            'ENTITY_TYPE_ID' => $ownerTypeId,
                            'ENTITY_ID' => $ownerId,
                            'AUTHOR_ID' => $authorId,
                            'TEXT' => $text,
                            'SETTINGS' => $settings,
                        ]);
                    }
                } catch (\Throwable $e) {
                    // ignore push errors
                }
            }
            return $noteId > 0 ? $noteId : null;
        } catch (\Throwable $e) {
            self::log('addNote error: ' . $e->getMessage());
            return null;
        }
    }

    /**
     * IM notification. $sticky = "confirm" type: stays unread in the notification panel
     * (bell badge) until the user presses the button; Bitrix then deletes it and fires
     * im:OnBeforeConfirmNotify, where we mark the share as acknowledged.
     */
    public static function notify(int $toUserId, string $message, string $tag, int $fromUserId = 0, bool $sticky = false): void
    {
        if ($toUserId <= 0 || trim($message) === '' || !Loader::includeModule('im')) {
            return;
        }
        try {
            $from = ($fromUserId > 0 && $fromUserId !== $toUserId) ? $fromUserId : 0;
            $fields = [
                'TO_USER_ID' => $toUserId,
                'FROM_USER_ID' => $from,
                'NOTIFY_TYPE' => $sticky ? IM_NOTIFY_CONFIRM : ($from > 0 ? IM_NOTIFY_FROM : IM_NOTIFY_SYSTEM),
                'NOTIFY_MODULE' => 'crm',
                'NOTIFY_EVENT' => 'other',
                'NOTIFY_TAG' => $tag,
                'NOTIFY_MESSAGE' => $message,
                'NOTIFY_MESSAGE_OUT' => preg_replace('~\[/?URL[^\]]*\]~i', '', $message),
            ];
            if ($sticky) {
                $fields['NOTIFY_BUTTONS'] = [
                    ['TITLE' => 'Got it', 'VALUE' => 'Y', 'TYPE' => 'accept'],
                ];
            }
            $id = \CIMNotify::Add($fields);
            if (!$id && $sticky) {
                // kernel refused the confirm variant (e.g. FROM_USER_ID not allowed) -> plain system notification
                $fields['FROM_USER_ID'] = 0;
                $fields['NOTIFY_TYPE'] = IM_NOTIFY_CONFIRM;
                $id = \CIMNotify::Add($fields);
                if (!$id) {
                    unset($fields['NOTIFY_BUTTONS']);
                    $fields['NOTIFY_TYPE'] = IM_NOTIFY_SYSTEM;
                    $id = \CIMNotify::Add($fields);
                }
            }
            self::log("NOTIFY to=$toUserId sticky=" . ($sticky ? 'Y' : 'N') . " tag=$tag id=" . var_export($id, true));
        } catch (\Throwable $e) {
            self::log('notify error: ' . $e->getMessage());
        }
    }

    /** Bitrix Pull push to one user; the page script re-reads its pending list on receipt. */
    public static function push(int $toUserId, array $params): void
    {
        try {
            if ($toUserId <= 0 || !Loader::includeModule('pull') || !class_exists('\Bitrix\Pull\Event')) {
                return;
            }
            \Bitrix\Pull\Event::add($toUserId, [
                'module_id' => 'crm',
                'command' => 'a7LeadShare',
                'params' => $params,
            ]);
        } catch (\Throwable $e) {
            self::log('push error: ' . $e->getMessage());
        }
    }

    /** im:OnBeforeConfirmNotify($module, $tag, $value, $notification) — "Got it" pressed. */
    public static function onConfirmNotify($module, $tag, $value, $notification = [])
    {
        try {
            if ($module !== 'crm' || !is_string($tag) || !str_starts_with($tag, 'A7_LEAD_SHARE|')) {
                return null;
            }
            $parts = explode('|', $tag);
            $leadId = (int) ($parts[1] ?? 0);
            $uid = (int) ($parts[2] ?? 0);
            if ($leadId > 0 && $uid > 0 && self::perms()) {
                A7LeadShare::ack($leadId, $uid);
            }
            return ['result' => true, 'text' => 'Lead share notification dismissed.'];
        } catch (\Throwable $e) {
            self::log('onConfirmNotify error: ' . $e->getMessage());
            return null;
        }
    }

    /* ------------------------------------------------------------------ */
    /* UI script                                                            */
    /* ------------------------------------------------------------------ */

    private static function injectJs(): void
    {
        global $APPLICATION;
        try {
            if (PHP_SAPI === 'cli' || !is_object($APPLICATION) || self::currentUserId() <= 0) {
                return;
            }
            // Every portal page gets the script (the share popup must appear on any tab);
            // the script itself only runs the lead-card logic on /crm/lead/ pages.
            if (!self::wantsJs()) {
                return;
            }
            $file = $_SERVER['DOCUMENT_ROOT'] . self::JS_PATH;
            if (!is_file($file)) {
                return;
            }
            $APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . filemtime($file));
        } catch (\Throwable $e) {
            self::log('injectJs error: ' . $e->getMessage());
        }
    }
}

A7LeadGuard::register();
