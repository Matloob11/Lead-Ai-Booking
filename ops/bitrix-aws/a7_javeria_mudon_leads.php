<?php
/**
 * A7 Javeria Mudon leads — U2297 can see, edit, and reassign Mudon leads
 * that are not assigned to the Hassan or Hussnain teams.
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_javeria_mudon_leads.php
 * Loaded from: php_interface/init.php
 *
 * Official community field only (Mudon). No other community is added.
 * Hassan / Hussnain roster from Team Divide.xlsx is excluded.
 * Javeria's own team, her CRM role, and the phone mask are not changed here.
 * No share rows and no new observers.
 */

use Bitrix\Main\Application;
use Bitrix\Main\EventManager;

if (defined('A7_JAVERIA_MUDON_LEADS_LOADED')) {
    return;
}
define('A7_JAVERIA_MUDON_LEADS_LOADED', true);

final class A7JaveriaMudonLeads
{
    public const USER_ID = 2297;
    public const LEAD = 1;
    public const TABLE = 'a7_javeria_mudon_lead';
    public const COMMUNITY_FIELD = 'UF_CRM_1770537051525';

    /**
     * Pakistan teams that must stay hidden: Hassan and Hussnain columns
     * in Team Divide.xlsx, plus those two leaders.
     *
     * @var array<int,string>
     */
    public const EXCLUDE = [
        2560 => 'Hassan T.L',
        2380 => 'Khazeema',
        2344 => 'Aila',
        2434 => 'Sapna',
        2291 => 'Uzma',
        2378 => 'Harm',
        2376 => 'Areeba',
        2379 => 'Eman',
        2303 => 'Ruqia',
        2551 => 'Hussnain',
        2381 => 'Mehnaz',
        2369 => 'Nimra',
        2371 => 'Tehreem',
        2535 => 'Mehreen',
        2368 => 'Esha',
        2367 => 'Warda',
        2351 => 'Momina Hamza',
        2350 => 'Irum',
    ];

    /** @var array<int,bool> */
    private static array $granted = [];
    private static bool $grantedLoaded = false;
    private static ?bool $tableOk = null;
    private static bool $applying = false;

    public static function register(): void
    {
        try {
            self::ensureTable();
            $em = EventManager::getInstance();
            $em->addEventHandler('crm', 'OnAfterCrmLeadAdd', [__CLASS__, 'onAfterLeadSave']);
            $em->addEventHandler('crm', 'OnAfterCrmLeadUpdate', [__CLASS__, 'onAfterLeadSave']);
            $em->addEventHandler('crm', 'OnAfterCrmLeadDelete', [__CLASS__, 'onAfterLeadDelete']);
        } catch (\Throwable $e) {
            self::log('register error: ' . $e->getMessage());
        }
    }

    public static function isGranted(int $leadId): bool
    {
        if ($leadId <= 0 || !self::tableOk()) {
            return false;
        }
        self::loadGranted();
        return isset(self::$granted[$leadId]);
    }

    public static function onAfterLeadSave(&$arFields): void
    {
        if (self::$applying || !is_array($arFields)) {
            return;
        }
        $id = (int) ($arFields['ID'] ?? 0);
        if ($id <= 0) {
            return;
        }
        try {
            self::syncLead($id);
        } catch (\Throwable $e) {
            self::log("syncLead $id error: " . $e->getMessage());
        }
    }

    public static function onAfterLeadDelete($id): void
    {
        $leadId = (int) $id;
        if ($leadId <= 0) {
            return;
        }
        try {
            self::revoke($leadId);
        } catch (\Throwable $e) {
            self::log("revoke $leadId error: " . $e->getMessage());
        }
    }

    public static function syncLead(int $leadId): bool
    {
        if (self::$applying) {
            return self::isGranted($leadId);
        }
        self::$applying = true;
        try {
            $row = self::loadLeadRow($leadId);
            if (!$row || !self::matches($row, $row)) {
                self::revoke($leadId);
                return false;
            }
            self::grant($leadId, (int) $row['ASSIGNED_BY_ID']);
            return true;
        } finally {
            self::$applying = false;
        }
    }

    public static function matches(array $lead, array $uf): bool
    {
        if (self::officialCommunity($uf) !== 'mudon') {
            return false;
        }
        $assigned = (int) ($lead['ASSIGNED_BY_ID'] ?? 0);
        return !isset(self::EXCLUDE[$assigned]);
    }

    public static function backfill(): array
    {
        self::ensureTable();
        $c = Application::getConnection();
        $field = self::COMMUNITY_FIELD;
        $sql = "SELECT l.ID, l.ASSIGNED_BY_ID, l.STATUS_ID, u.$field AS $field
                FROM b_crm_lead l
                JOIN b_uts_crm_lead u ON u.VALUE_ID = l.ID
                WHERE LOWER(TRIM(IFNULL(u.$field, ''))) = 'mudon'";
        $scanned = 0;
        $granted = 0;
        $skipped = 0;
        $q = $c->query($sql);
        while ($row = $q->fetch()) {
            $scanned++;
            if (!self::matches($row, $row)) {
                $skipped++;
                self::revoke((int) $row['ID']);
                continue;
            }
            self::grant((int) $row['ID'], (int) $row['ASSIGNED_BY_ID']);
            $granted++;
        }
        self::revokeStale();
        return ['scanned' => $scanned, 'granted' => $granted, 'skipped' => $skipped];
    }

    public static function ensureTable(): void
    {
        $c = Application::getConnection();
        if (!$c->isTableExists(self::TABLE)) {
            $c->queryExecute(
                'CREATE TABLE ' . self::TABLE . ' (
                    LEAD_ID INT UNSIGNED NOT NULL,
                    ASSIGNED_BY_ID INT UNSIGNED NOT NULL,
                    UPDATED DATETIME NOT NULL,
                    PRIMARY KEY (LEAD_ID),
                    KEY IX_ASSIGNED (ASSIGNED_BY_ID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
            );
        }
        self::$tableOk = true;
    }

    private static function grant(int $leadId, int $assignedById): void
    {
        self::ensureTable();
        $c = Application::getConnection();
        $c->queryExecute(sprintf(
            'INSERT INTO %s (LEAD_ID, ASSIGNED_BY_ID, UPDATED)
             VALUES (%d, %d, NOW())
             ON DUPLICATE KEY UPDATE ASSIGNED_BY_ID=%d, UPDATED=NOW()',
            self::TABLE,
            $leadId,
            $assignedById,
            $assignedById
        ));
        self::$granted[$leadId] = true;
        self::ensureAccessAttr($leadId, $assignedById);
    }

    private static function revoke(int $leadId): void
    {
        if ($leadId <= 0) {
            return;
        }
        if (self::tableOk()) {
            Application::getConnection()->queryExecute(sprintf(
                'DELETE FROM %s WHERE LEAD_ID=%d',
                self::TABLE,
                $leadId
            ));
        }
        unset(self::$granted[$leadId]);
        self::removeAccessAttr($leadId);
    }

    private static function revokeStale(): void
    {
        if (!self::tableOk()) {
            return;
        }
        $c = Application::getConnection();
        $keep = [];
        $q = $c->query('SELECT LEAD_ID FROM ' . self::TABLE);
        while ($r = $q->fetch()) {
            $id = (int) $r['LEAD_ID'];
            $row = self::loadLeadRow($id);
            if ($row && self::matches($row, $row)) {
                $keep[$id] = true;
                continue;
            }
            self::revoke($id);
        }
        self::$granted = $keep;
        self::$grantedLoaded = true;
    }

    private static function ensureAccessAttr(int $leadId, int $assignedById): void
    {
        if ($assignedById === self::USER_ID) {
            return;
        }
        $c = Application::getConnection();
        $row = $c->query('SELECT ID, STATUS_ID FROM b_crm_lead WHERE ID=' . $leadId)->fetch();
        if (!$row) {
            return;
        }
        $exists = $c->query(sprintf(
            'SELECT ID FROM b_crm_access_attr_lead WHERE ENTITY_ID=%d AND USER_ID=%d LIMIT 1',
            $leadId,
            self::USER_ID
        ))->fetch();
        if ($exists) {
            return;
        }
        $step = $c->getSqlHelper()->forSql((string) ($row['STATUS_ID'] ?: 'NEW'), 50);
        $c->queryExecute(sprintf(
            "INSERT INTO b_crm_access_attr_lead
                (ENTITY_ID, CATEGORY_ID, USER_ID, IS_OPENED, IS_ALWAYS_READABLE, PROGRESS_STEP)
             VALUES (%d, 0, %d, 'N', 'N', '%s')",
            $leadId,
            self::USER_ID,
            $step
        ));
    }

    private static function removeAccessAttr(int $leadId): void
    {
        $c = Application::getConnection();
        $assigned = $c->query('SELECT ASSIGNED_BY_ID FROM b_crm_lead WHERE ID=' . $leadId)->fetch();
        if ($assigned && (int) $assigned['ASSIGNED_BY_ID'] === self::USER_ID) {
            return;
        }
        $c->queryExecute(sprintf(
            'DELETE FROM b_crm_access_attr_lead WHERE ENTITY_ID=%d AND USER_ID=%d',
            $leadId,
            self::USER_ID
        ));
    }

    private static function loadGranted(): void
    {
        if (self::$grantedLoaded || !self::tableOk()) {
            return;
        }
        self::$granted = [];
        $q = Application::getConnection()->query('SELECT LEAD_ID FROM ' . self::TABLE);
        while ($r = $q->fetch()) {
            self::$granted[(int) $r['LEAD_ID']] = true;
        }
        self::$grantedLoaded = true;
    }

    private static function tableOk(): bool
    {
        if (self::$tableOk === null) {
            try {
                self::$tableOk = Application::getConnection()->isTableExists(self::TABLE);
            } catch (\Throwable $e) {
                self::$tableOk = false;
            }
        }
        return (bool) self::$tableOk;
    }

    private static function loadLeadRow(int $leadId): ?array
    {
        $c = Application::getConnection();
        $field = self::COMMUNITY_FIELD;
        $row = $c->query(
            "SELECT l.ID, l.ASSIGNED_BY_ID, l.STATUS_ID, u.$field AS $field
             FROM b_crm_lead l
             LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID = l.ID
             WHERE l.ID=" . $leadId
        )->fetch();
        return $row ?: null;
    }

    private static function officialCommunity(array $uf): string
    {
        return strtolower(trim((string) ($uf[self::COMMUNITY_FIELD] ?? '')));
    }

    private static function log(string $msg): void
    {
        if (function_exists('AddMessage2Log')) {
            AddMessage2Log('[A7JaveriaMudonLeads] ' . $msg, 'a7.javeria.mudon');
        }
    }
}

A7JaveriaMudonLeads::register();
