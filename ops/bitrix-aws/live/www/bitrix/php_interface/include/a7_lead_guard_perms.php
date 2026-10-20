<?php
/**
 * A7 Lead Guard — shared-lead write permission (Bitrix service override).
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_lead_guard_perms.php
 * Registered via: /home/bitrix/www/bitrix/.settings_extra.php
 *     'services' => ['value' => ['crm.service.container' => ['className' => 'A7CrmContainer']]]
 *
 * Bitrix resolves \Bitrix\Crm\Service\Container through the ServiceLocator, and the
 * site-level registration wins over the crm module's own one (registerByModuleSettings
 * skips identifiers that already exist). We replace only these decisions:
 *
 *     Item::canUpdateItemIdentifier(lead)  ->  true when the user is a *shared* user of
 *                                              that lead (row in a7_lead_share + still an
 *                                              observer on the lead).
 *     Neha (U2251) read + update           ->  true only for leads already in
 *                                              a7_neha_community_lead (the ones on screen).
 *                                              Does not grant new leads, delete, or export.
 *     Javeria (U2297) read + update        ->  true only for Mudon leads already in
 *                                              a7_javeria_mudon_lead. Hassan and Hussnain
 *                                              teams are not in that table. Delete stays off.
 *     Booking stage (2026-10-20)           ->  anyone who can READ a lead that is on the
 *                                              Booking stage (CONVERTED) may UPDATE it; the
 *                                              guard then lets only the five booking fields
 *                                              change (A7LeadShare::bookingGrant / bookingOnly).
 *                                              A team lead opening a colleague's booked lead
 *                                              fills Rent or Sale, Commission Zone, Commission
 *                                              Document, Commission Status and the voucher no.
 *
 * Delete stays blocked for everybody by the guard. Which fields a shared user may
 * actually change is enforced in A7LeadGuard::onBeforeLeadUpdate.
 *
 * "Shared" here means shared AFTER the guard went live (2026-09-14): the share flow in
 * A7LeadGuard writes a row into a7_lead_share. The 800+ historical observer rows on the
 * portal keep read-only behaviour.
 */

use Bitrix\Crm\ItemIdentifier;
use Bitrix\Crm\Service\Container;
use Bitrix\Crm\Service\UserPermissions;
use Bitrix\Crm\Service\UserPermissions\EntityPermissions\Item;

// NOTE: no "already loaded -> return" guard here. PHP hoists classes whose parent is
// already loaded at compile time, so such a guard would fire after A7CrmContainer was
// declared and skip the remaining classes. Loaders use require_once instead.

final class A7CrmContainer extends Container
{
    protected function createUserPermissions(int $userId): UserPermissions
    {
        return new A7UserPermissions($userId);
    }
}

class A7UserPermissions extends UserPermissions
{
    /** @var A7ItemPermissions|null */
    private $a7Item = null;

    /**
     * Activities (to-do, reminder, call, task …) still use the LEGACY check
     * CCrmAuthorizationHelper::checkPermissionForTypeAndAttributes(), which does not go
     * through item()->canUpdateItemIdentifier(). It does, however, call isAdmin() on this
     * object first. So: for a WRITE check on a LEAD that is shared with this user, answer
     * "yes" here. Read/delete and every other entity type are untouched.
     */
    public function isAdmin(): bool
    {
        if (parent::isAdmin()) {
            return true;
        }
        try {
            return A7LeadShare::legacyWriteGrant($this->getUserId());
        } catch (\Throwable $e) {
            return false;
        }
    }

    public function item(): Item
    {
        if (!$this->a7Item) {
            // Bitrix builds Item from private dependencies; take them from the stock
            // Item via reflection so we stay in sync with whatever the kernel wires.
            $base = parent::item();
            try {
                $ref = new \ReflectionClass(Item::class);
                $deps = [];
                foreach (['permissionsManager', 'admin', 'entityAdmin', 'entityType', 'catalogEntityItem', 'saleEntityItem'] as $p) {
                    $prop = $ref->getProperty($p);
                    $prop->setAccessible(true);
                    $deps[] = $prop->getValue($base);
                }
                $this->a7Item = new A7ItemPermissions($this->getUserId(), ...$deps);
            } catch (\Throwable $e) {
                // Kernel changed its internals: fall back to stock behaviour (no shared write).
                return $base;
            }
        }
        return $this->a7Item;
    }
}

class A7ItemPermissions extends Item
{
    private int $a7UserId;

    public function __construct(int $userId, ...$args)
    {
        $this->a7UserId = $userId;
        parent::__construct(...$args);
    }

    public function canReadItemIdentifier(ItemIdentifier $itemIdentifier): bool
    {
        if (parent::canReadItemIdentifier($itemIdentifier)) {
            return true;
        }
        try {
            return A7LeadShare::nehaGrantedLead(
                $this->a7UserId,
                $itemIdentifier->getEntityTypeId(),
                $itemIdentifier->getEntityId()
            ) || A7LeadShare::javeriaMudonLead(
                $this->a7UserId,
                $itemIdentifier->getEntityTypeId(),
                $itemIdentifier->getEntityId()
            );
        } catch (\Throwable $e) {
            return false;
        }
    }

    public function canUpdateItemIdentifier(ItemIdentifier $itemIdentifier): bool
    {
        if (parent::canUpdateItemIdentifier($itemIdentifier)) {
            return true;
        }
        try {
            if (A7LeadShare::mayUpdate($this->a7UserId, $itemIdentifier->getEntityTypeId(), $itemIdentifier->getEntityId())) {
                return true;
            }
            if (A7LeadShare::nehaGrantedLead(
                $this->a7UserId,
                $itemIdentifier->getEntityTypeId(),
                $itemIdentifier->getEntityId()
            ) || A7LeadShare::javeriaMudonLead(
                $this->a7UserId,
                $itemIdentifier->getEntityTypeId(),
                $itemIdentifier->getEntityId()
            )) {
                return true;
            }
            // The booking fields of a lead on the Booking stage: anyone who can read it (the guard limits the fields).
            return A7LeadShare::bookingGrant(
                $this->a7UserId,
                $itemIdentifier->getEntityTypeId(),
                $itemIdentifier->getEntityId(),
                fn() => parent::canReadItemIdentifier($itemIdentifier)
            );
        } catch (\Throwable $e) {
            return false;
        }
    }

    /** The kernel's own answers, with none of our grants: the guard tells a booking-only update by them. */
    public function stockCanRead(ItemIdentifier $itemIdentifier): bool
    {
        return parent::canReadItemIdentifier($itemIdentifier);
    }

    public function stockCanUpdate(ItemIdentifier $itemIdentifier): bool
    {
        return parent::canUpdateItemIdentifier($itemIdentifier);
    }
}

/**
 * Registry of leads shared through the guard (table a7_lead_share) + the decision helper.
 */
final class A7LeadShare
{
    public const TABLE = 'a7_lead_share';
    public const LEAD = 1;
    /** The stage on which anyone who can open the lead may fill its booking fields (Booking = CONVERTED). */
    public const BOOKING_STAGE = 'CONVERTED';
    /** The booking fields (a7_booking_fields_setup.php); the guard config key booking_fields overrides the list. */
    public const BOOKING_FIELDS = [
        'UF_CRM_A7_BOOKING_RENT_SALE', 'UF_CRM_A7_COMMISSION_ZONE', 'UF_CRM_A7_COMMISSION_DOC',
        'UF_CRM_A7_COMMISSION_STATUS', 'UF_CRM_A7_COMMISSION_VOUCHER',
    ];

    /** @var array<string,bool> per-request cache "uid:lead" => allowed */
    private static array $cache = [];
    /** @var array<string,bool> per-request cache "uid:lead" => the booking-fields grant applies */
    private static array $bookingGranted = [];
    /** @var array<int,bool> per-request cache leadId => on the Booking stage */
    private static array $bookingLead = [];
    /** @var array<int,array<int,bool>> per-request preload: userId => [leadId => true] */
    private static array $userLeads = [];
    /** @var bool|null table exists (checked once per request) */
    private static ?bool $tableOk = null;

    private static function tableOk(): bool
    {
        if (self::$tableOk === null) {
            self::$tableOk = \Bitrix\Main\Application::getConnection()->isTableExists(self::TABLE);
        }
        return self::$tableOk;
    }

    /** All leads shared with a user — ONE query per request, then memory only. */
    public static function leadsOf(int $userId): array
    {
        if ($userId <= 0 || !self::tableOk()) {
            return [];
        }
        if (!isset(self::$userLeads[$userId])) {
            $set = [];
            $q = \Bitrix\Main\Application::getConnection()->query(sprintf('SELECT LEAD_ID FROM %s WHERE USER_ID=%d', self::TABLE, $userId));
            while ($r = $q->fetch()) {
                $set[(int) $r['LEAD_ID']] = true;
            }
            self::$userLeads[$userId] = $set;
        }
        return self::$userLeads[$userId];
    }

    public static function ensureTable(): void
    {
        $c = \Bitrix\Main\Application::getConnection();
        if (!$c->isTableExists(self::TABLE)) {
            $c->queryExecute(
                'CREATE TABLE ' . self::TABLE . ' (
                    LEAD_ID INT UNSIGNED NOT NULL,
                    USER_ID INT UNSIGNED NOT NULL,
                    SHARED_BY INT UNSIGNED NOT NULL DEFAULT 0,
                    CREATED DATETIME NOT NULL,
                    ACKED DATETIME NULL DEFAULT NULL,
                    PRIMARY KEY (LEAD_ID, USER_ID),
                    KEY IX_USER (USER_ID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
            );
            self::$tableOk = true;
            return;
        }
        // v1.3: ACKED column (popup dismissed / "Got it" pressed)
        $col = $c->query("SHOW COLUMNS FROM " . self::TABLE . " LIKE 'ACKED'")->fetch();
        if (!$col) {
            $c->queryExecute('ALTER TABLE ' . self::TABLE . ' ADD COLUMN ACKED DATETIME NULL DEFAULT NULL');
        }
    }

    /** Mark a share as acknowledged (popup dismissed or "Got it" pressed). */
    public static function ack(int $leadId, int $userId): void
    {
        if ($leadId <= 0 || $userId <= 0 || !self::tableOk()) {
            return;
        }
        \Bitrix\Main\Application::getConnection()->queryExecute(sprintf(
            'UPDATE %s SET ACKED=NOW() WHERE LEAD_ID=%d AND USER_ID=%d AND ACKED IS NULL', self::TABLE, $leadId, $userId
        ));
    }

    /**
     * Shares of a user that were not acknowledged yet: [['lead'=>id,'by'=>uid,'at'=>'Y-m-d H:i'], ...]
     * Only shares made after $since (config popup_since, set at deploy) are considered.
     */
    public static function pendingOf(int $userId, string $since = ''): array
    {
        if ($userId <= 0 || !self::tableOk()) {
            return [];
        }
        $out = [];
        $c = \Bitrix\Main\Application::getConnection();
        $sinceSql = '';
        if ($since !== '' && ($ts = strtotime($since)) !== false) {
            $sinceSql = " AND CREATED >= '" . date('Y-m-d H:i:s', $ts) . "'";
        }
        $q = $c->query(sprintf(
            'SELECT LEAD_ID, SHARED_BY, CREATED FROM %s WHERE USER_ID=%d AND ACKED IS NULL%s ORDER BY CREATED DESC LIMIT 20', self::TABLE, $userId, $sinceSql
        ));
        while ($r = $q->fetch()) {
            $created = $r['CREATED'];
            $out[] = [
                'lead' => (int) $r['LEAD_ID'],
                'by' => (int) $r['SHARED_BY'],
                'at' => is_object($created) && method_exists($created, 'format') ? $created->format('d.m.Y H:i') : (string) $created,
            ];
        }
        return $out;
    }

    public static function add(int $leadId, int $userId, int $sharedBy): void
    {
        if ($leadId <= 0 || $userId <= 0) {
            return;
        }
        $c = \Bitrix\Main\Application::getConnection();
        $c->queryExecute(sprintf(
            'INSERT IGNORE INTO %s (LEAD_ID, USER_ID, SHARED_BY, CREATED) VALUES (%d, %d, %d, NOW())',
            self::TABLE, $leadId, $userId, $sharedBy
        ));
        unset(self::$cache["$userId:$leadId"], self::$userLeads[$userId]);
    }

    public static function remove(int $leadId, int $userId): void
    {
        $c = \Bitrix\Main\Application::getConnection();
        $c->queryExecute(sprintf('DELETE FROM %s WHERE LEAD_ID=%d AND USER_ID=%d', self::TABLE, $leadId, $userId));
        unset(self::$cache["$userId:$leadId"], self::$userLeads[$userId]);
    }

    /** Is this user a guard-shared user of this lead (row present)? Memory lookup after the first call. */
    public static function isShared(int $leadId, int $userId): bool
    {
        if ($leadId <= 0 || $userId <= 0) {
            return false;
        }
        return isset(self::leadsOf($userId)[$leadId]);
    }

    /** Which of the given leads are guard-shared (with anyone)? One query. */
    public static function sharedAmong(array $leadIds): array
    {
        $ids = array_values(array_unique(array_filter(array_map('intval', $leadIds))));
        if (!$ids || !self::tableOk()) {
            return [];
        }
        $out = [];
        $q = \Bitrix\Main\Application::getConnection()->query(sprintf('SELECT LEAD_ID, USER_ID FROM %s WHERE LEAD_ID IN (%s)', self::TABLE, implode(',', $ids)));
        while ($r = $q->fetch()) {
            $out[(int) $r['LEAD_ID']][] = (int) $r['USER_ID'];
        }
        return $out;
    }

    /** Shared users of a lead (ids). */
    public static function usersOf(int $leadId): array
    {
        if ($leadId <= 0 || !self::tableOk()) {
            return [];
        }
        $out = [];
        $q = \Bitrix\Main\Application::getConnection()->query(sprintf('SELECT USER_ID FROM %s WHERE LEAD_ID=%d', self::TABLE, $leadId));
        while ($r = $q->fetch()) {
            $out[] = (int) $r['USER_ID'];
        }
        return $out;
    }

    /**
     * Neha (U2251) may read/update a lead only when it is already in a7_neha_community_lead.
     * That is the set already on her screen. Matching a community name is not enough.
     */
    public static function nehaGrantedLead(int $userId, int $entityTypeId, int $entityId): bool
    {
        if ($userId !== 2251 || $entityTypeId !== self::LEAD || $entityId <= 0) {
            return false;
        }
        $path = '/home/bitrix/www/bitrix/php_interface/include/a7_neha_community_leads.php';
        if (!class_exists('A7NehaCommunityLeads', false) && is_file($path)) {
            require_once $path;
        }
        return class_exists('A7NehaCommunityLeads') && A7NehaCommunityLeads::isGranted($entityId);
    }

    /**
     * Javeria (U2297) may read/update a lead only when it is already in
     * a7_javeria_mudon_lead (Mudon, and not a Hassan/Hussnain assignee).
     */
    public static function javeriaMudonLead(int $userId, int $entityTypeId, int $entityId): bool
    {
        if ($userId !== 2297 || $entityTypeId !== self::LEAD || $entityId <= 0) {
            return false;
        }
        $path = '/home/bitrix/www/bitrix/php_interface/include/a7_javeria_mudon_leads.php';
        if (!class_exists('A7JaveriaMudonLeads', false) && is_file($path)) {
            require_once $path;
        }
        return class_exists('A7JaveriaMudonLeads') && A7JaveriaMudonLeads::isGranted($entityId);
    }

    public static function legacyWriteGrant(int $userId): bool
    {
        if ($userId <= 0) {
            return false;
        }
        $hasShare = (bool) self::leadsOf($userId);
        // The booking grant needs the backtrace for every non-admin, so only on a request that can carry a lead write.
        $booking = self::requestMayWriteLead();
        if (!$hasShare && !$booking && $userId !== 2251 && $userId !== 2297) {
            return false;
        }
        foreach (debug_backtrace(0, 12) as $f) {
            if (($f['class'] ?? '') !== 'CCrmAuthorizationHelper' || ($f['function'] ?? '') !== 'checkPermissionForTypeAndAttributes') {
                continue;
            }
            $args = $f['args'] ?? [];
            $perm = strtoupper((string) ($args[0] ?? ''));
            $type = $args[1] ?? '';
            $type = is_numeric($type) ? (string) \CCrmOwnerType::ResolveName((int) $type) : strtoupper((string) $type);
            $id = (int) ($args[2] ?? 0);
            if ($type !== 'LEAD' || $id <= 0) {
                return false;
            }
            if ($perm === 'WRITE' && $hasShare && self::mayUpdate($userId, self::LEAD, $id)) {
                return true;
            }
            if (in_array($perm, ['READ', 'WRITE'], true) && self::nehaGrantedLead($userId, self::LEAD, $id)) {
                return true;
            }
            if (in_array($perm, ['READ', 'WRITE'], true) && self::javeriaMudonLead($userId, self::LEAD, $id)) {
                return true;
            }
            if ($perm === 'WRITE' && $booking && self::bookingGrant($userId, self::LEAD, $id, static fn() => self::stockRead($userId, $id))) {
                return true;
            }
            return false;
        }
        return false;
    }

    /* ---- the booking-fields grant (2026-10-20) ------------------------------------------------------------- */

    /** The booking fields, uppercased: the guard config's booking_fields when set, else BOOKING_FIELDS. */
    public static function bookingFields(): array
    {
        $fields = [];
        if (class_exists('A7LeadGuard', false)) {
            $fields = (array) (A7LeadGuard::config()['booking_fields'] ?? []);
        }
        $fields = array_values(array_filter(array_map(static fn($f) => strtoupper(trim((string) $f)), $fields)));
        return $fields ?: self::BOOKING_FIELDS;
    }

    /** Is the lead on the Booking stage now (the stored stage, never the one an update brings)? One query per lead. */
    public static function isBookingLead(int $leadId): bool
    {
        if ($leadId <= 0) {
            return false;
        }
        if (!isset(self::$bookingLead[$leadId])) {
            $row = \Bitrix\Main\Application::getConnection()->query('SELECT STATUS_ID FROM b_crm_lead WHERE ID=' . $leadId)->fetch();
            self::$bookingLead[$leadId] = is_array($row) && (string) ($row['STATUS_ID'] ?? '') === self::BOOKING_STAGE;
        }
        return self::$bookingLead[$leadId];
    }

    /**
     * The booking-fields grant: a lead already on the Booking stage may be updated by anyone who can read it, and
     * A7LeadGuard::onBeforeLeadUpdate then lets only the booking fields change. ``$canRead`` is the kernel's own read
     * check for this user and lead (A7ItemPermissions::stockCanRead), never one that comes back through these grants.
     */
    public static function bookingGrant(int $userId, int $entityTypeId, int $entityId, callable $canRead): bool
    {
        if ($entityTypeId !== self::LEAD || $userId <= 0 || $entityId <= 0 || !self::isBookingLead($entityId)) {
            return false;
        }
        $key = "$userId:$entityId";
        if (!isset(self::$bookingGranted[$key])) {
            try {
                self::$bookingGranted[$key] = (bool) $canRead();
            } catch (\Throwable $e) {
                self::$bookingGranted[$key] = false;
            }
        }
        return self::$bookingGranted[$key];
    }

    /**
     * Is this update open to the user through the booking grant alone — no right of their own, no share, no
     * Neha/Javeria grant? The guard then limits the fields. False when the kernel grants the update itself.
     */
    public static function bookingOnly(int $userId, int $leadId): bool
    {
        if ($userId <= 0 || $leadId <= 0 || !self::isBookingLead($leadId)) {
            return false;
        }
        try {
            if (self::stockUpdate($userId, $leadId) || self::mayUpdate($userId, self::LEAD, $leadId)
                || self::nehaGrantedLead($userId, self::LEAD, $leadId) || self::javeriaMudonLead($userId, self::LEAD, $leadId)) {
                return false;
            }
            return self::stockRead($userId, $leadId);
        } catch (\Throwable $e) {
            return false;
        }
    }

    /** The kernel's own read answer for a user and lead (our item permissions' parent; the legacy helper if not ours). */
    public static function stockRead(int $userId, int $leadId): bool
    {
        $item = Container::getInstance()->getUserPermissions($userId)->item();
        if ($item instanceof A7ItemPermissions) {
            return $item->stockCanRead(new ItemIdentifier(self::LEAD, $leadId));
        }
        return (bool) \CCrmLead::CheckReadPermission($leadId, \CCrmPerms::GetUserPermissions($userId));
    }

    public static function stockUpdate(int $userId, int $leadId): bool
    {
        $item = Container::getInstance()->getUserPermissions($userId)->item();
        if ($item instanceof A7ItemPermissions) {
            return $item->stockCanUpdate(new ItemIdentifier(self::LEAD, $leadId));
        }
        return (bool) \CCrmLead::CheckUpdatePermission($leadId, \CCrmPerms::GetUserPermissions($userId));
    }

    /** A request that can carry a lead write: the legacy permission check is then worth a backtrace for everyone. */
    public static function requestMayWriteLead(): bool
    {
        static $may = null;
        if ($may === null) {
            $method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? ''));
            $hay = (string) ($_SERVER['SCRIPT_NAME'] ?? '') . ' ' . (string) ($_SERVER['REQUEST_URI'] ?? '');
            $may = PHP_SAPI === 'cli'
                || ($method === 'POST' && (bool) preg_match('~/bitrix/(?:components/bitrix/crm\.[a-z0-9_.]+/|services/main/ajax\.php)|/rest/~i', $hay));
        }
        return $may;
    }

    /**
     * The one extra permission: a shared user may UPDATE the lead (so that stage changes,
     * own comments and activities work). Requires: entity is a Lead, a share row exists,
     * and the user is still an observer on the lead (removing the observer ends the share).
     */
    public static function mayUpdate(int $userId, int $entityTypeId, int $entityId): bool
    {
        if ($entityTypeId !== self::LEAD || $userId <= 0 || $entityId <= 0) {
            return false;
        }
        $key = "$userId:$entityId";
        if (isset(self::$cache[$key])) {
            return self::$cache[$key];
        }
        $ok = false;
        if (self::isShared($entityId, $userId) && class_exists('\Bitrix\Crm\Observer\ObserverManager')) {
            $observers = array_map('intval', \Bitrix\Crm\Observer\ObserverManager::getEntityObserverIDs(self::LEAD, $entityId));
            $ok = in_array($userId, $observers, true);
        }
        self::$cache[$key] = $ok;
        return $ok;
    }
}
