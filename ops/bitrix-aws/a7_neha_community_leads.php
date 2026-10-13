<?php
/**
 * A7 Neha community leads — Damac Lagoons + Serena visibility for U2251.
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_neha_community_leads.php
 * Loaded from: php_interface/init.php
 *
 * Neha stays Agent ATTR=A. Responsible person is never changed.
 * List/kanban: extra b_crm_access_attr_lead row USER_ID=2251 (register() wipes it; we restore).
 * Card read/write: A7ItemPermissions delegates to A7NehaCommunityLeads::mayAccess.
 * No a7_lead_share rows (no share popups). No observers (no IM / observer UI).
 * ASSIGNED_BY_ID stays locked when she is not the assignee.
 */

use Bitrix\Main\Application;
use Bitrix\Main\EventManager;

if (defined('A7_NEHA_COMMUNITY_LEADS_LOADED')) {
    return;
}
define('A7_NEHA_COMMUNITY_LEADS_LOADED', true);

final class A7NehaCommunityLeads
{
    public const USER_ID = 2251;
    public const LEAD = 1;
    public const TABLE = 'a7_neha_community_lead';
    public const COMMUNITY_FIELD = 'UF_CRM_1770537051525';
    public const PROJECT_FIELD = 'UF_CRM_1731838049723';
    public const AREA_FIELD = 'UF_CRM_1733420840732';

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
            $em->addEventHandler('crm', 'OnBeforeCrmLeadUpdate', [__CLASS__, 'onBeforeLeadUpdate']);
            $em->addEventHandler('crm', 'OnAfterCrmLeadDelete', [__CLASS__, 'onAfterLeadDelete']);
        } catch (\Throwable $e) {
            self::log('register error: ' . $e->getMessage());
        }
    }

    public static function mayAccess(int $userId, int $entityTypeId, int $entityId): bool
    {
        if ($userId !== self::USER_ID || $entityTypeId !== self::LEAD || $entityId <= 0) {
            return false;
        }
        if (self::isGranted($entityId)) {
            return true;
        }
        return self::leadMatches($entityId);
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

    public static function onBeforeLeadUpdate(&$arFields)
    {
        global $APPLICATION;
        try {
            $id = (int) ($arFields['ID'] ?? 0);
            if ($id <= 0 || !is_array($arFields) || !array_key_exists('ASSIGNED_BY_ID', $arFields)) {
                return true;
            }
            $uid = self::currentUserId();
            if ($uid !== self::USER_ID || !self::mayAccess($uid, self::LEAD, $id)) {
                return true;
            }
            $row = self::loadLeadRow($id);
            if (!$row) {
                return true;
            }
            $oldAssigned = (int) $row['ASSIGNED_BY_ID'];
            if ($oldAssigned === self::USER_ID) {
                return true;
            }
            if ((int) $arFields['ASSIGNED_BY_ID'] !== $oldAssigned) {
                if (isset($APPLICATION) && method_exists($APPLICATION, 'ThrowException')) {
                    $APPLICATION->ThrowException(
                        'You can edit this community lead, but the responsible person cannot be changed.',
                        'A7_NEHA_ASSIGNED_LOCKED'
                    );
                }
                return false;
            }
        } catch (\Throwable $e) {
            self::log('onBeforeLeadUpdate error: ' . $e->getMessage());
        }
        return true;
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
            if (!$row) {
                self::revoke($leadId);
                return false;
            }
            if (!self::matches($row, $row)) {
                self::revoke($leadId);
                return false;
            }
            self::grant($leadId, (int) $row['ASSIGNED_BY_ID'], self::matchReason($row, $row));
            return true;
        } finally {
            self::$applying = false;
        }
    }

    public static function matches(array $lead, array $uf): bool
    {
        $official = self::officialCommunity($uf);
        if (in_array($official, ['damac hills', 'damac hills 2', 'city walk lagoon', 'lagoons city walk'], true)) {
            return false;
        }
        if ($official === 'damac lagoons' || $official === 'serena') {
            return true;
        }
        $hay = self::haystack($lead, $uf);
        if (preg_match('/damac\s+hills|city\s+walk\s+lagoon|lagoons?\s+city\s+walk/', $hay)
            && !preg_match('/damac\s+lagoons?\b/', $hay)
            && !preg_match('/\bserena\b/', $hay)
        ) {
            return false;
        }
        return (bool) preg_match('/damac\s+lagoons?\b/', $hay) || (bool) preg_match('/\bserena\b/', $hay);
    }

    public static function matchReason(array $lead, array $uf): string
    {
        $official = self::officialCommunity($uf);
        if ($official === 'damac lagoons' || $official === 'serena') {
            return 'community:' . str_replace(' ', '_', $official);
        }
        return 'text';
    }

    public static function backfill(): array
    {
        self::ensureTable();
        $c = Application::getConnection();
        $sql = "SELECT l.ID, l.TITLE, l.ASSIGNED_BY_ID, l.STATUS_ID,
                       u." . self::COMMUNITY_FIELD . " AS " . self::COMMUNITY_FIELD . ",
                       u." . self::PROJECT_FIELD . " AS " . self::PROJECT_FIELD . ",
                       u." . self::AREA_FIELD . " AS " . self::AREA_FIELD . "
                FROM b_crm_lead l
                LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID = l.ID
                WHERE LOWER(TRIM(IFNULL(u." . self::COMMUNITY_FIELD . ", ''))) IN ('damac lagoons', 'serena')
                   OR LOWER(CONCAT_WS(' ', l.TITLE, IFNULL(u." . self::PROJECT_FIELD . ", ''), IFNULL(u." . self::AREA_FIELD . ", ''))) LIKE '%damac lagoon%'
                   OR LOWER(CONCAT_WS(' ', l.TITLE, IFNULL(u." . self::PROJECT_FIELD . ", ''), IFNULL(u." . self::AREA_FIELD . ", ''))) LIKE '%serena%'";
        $scanned = 0;
        $granted = 0;
        $skipped = 0;
        $q = $c->query($sql);
        while ($row = $q->fetch()) {
            $scanned++;
            $id = (int) $row['ID'];
            if (!self::matches($row, $row)) {
                $skipped++;
                continue;
            }
            self::grant($id, (int) $row['ASSIGNED_BY_ID'], self::matchReason($row, $row));
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
                    MATCH_REASON VARCHAR(64) NOT NULL,
                    UPDATED DATETIME NOT NULL,
                    PRIMARY KEY (LEAD_ID),
                    KEY IX_ASSIGNED (ASSIGNED_BY_ID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
            );
        }
        self::$tableOk = true;
    }

    private static function grant(int $leadId, int $assignedById, string $reason): void
    {
        self::ensureTable();
        $c = Application::getConnection();
        $reason = substr(preg_replace('/[^a-z0-9:_-]/', '', strtolower($reason)) ?: 'text', 0, 64);
        $c->queryExecute(sprintf(
            'INSERT INTO %s (LEAD_ID, ASSIGNED_BY_ID, MATCH_REASON, UPDATED)
             VALUES (%d, %d, \'%s\', NOW())
             ON DUPLICATE KEY UPDATE ASSIGNED_BY_ID=%d, MATCH_REASON=\'%s\', UPDATED=NOW()',
            self::TABLE,
            $leadId,
            $assignedById,
            $reason,
            $assignedById,
            $reason
        ));
        self::$granted[$leadId] = true;
        self::ensureAccessAttr($leadId);
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

    private static function ensureAccessAttr(int $leadId): void
    {
        $c = Application::getConnection();
        $row = $c->query('SELECT ID, ASSIGNED_BY_ID, STATUS_ID FROM b_crm_lead WHERE ID=' . $leadId)->fetch();
        if (!$row) {
            return;
        }
        if ((int) $row['ASSIGNED_BY_ID'] === self::USER_ID) {
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

    private static function leadMatches(int $leadId): bool
    {
        $row = self::loadLeadRow($leadId);
        return $row ? self::matches($row, $row) : false;
    }

    private static function loadLeadRow(int $leadId): ?array
    {
        $c = Application::getConnection();
        $row = $c->query(
            'SELECT l.ID, l.TITLE, l.ASSIGNED_BY_ID, l.STATUS_ID,
                    u.' . self::COMMUNITY_FIELD . ' AS ' . self::COMMUNITY_FIELD . ',
                    u.' . self::PROJECT_FIELD . ' AS ' . self::PROJECT_FIELD . ',
                    u.' . self::AREA_FIELD . ' AS ' . self::AREA_FIELD . '
             FROM b_crm_lead l
             LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID = l.ID
             WHERE l.ID=' . $leadId
        )->fetch();
        return $row ?: null;
    }

    private static function officialCommunity(array $uf): string
    {
        return strtolower(trim((string) ($uf[self::COMMUNITY_FIELD] ?? '')));
    }

    private static function haystack(array $lead, array $uf): string
    {
        return strtolower(trim(implode(' ', [
            (string) ($lead['TITLE'] ?? ''),
            (string) ($uf[self::COMMUNITY_FIELD] ?? ''),
            (string) ($uf[self::PROJECT_FIELD] ?? ''),
            (string) ($uf[self::AREA_FIELD] ?? ''),
        ])));
    }

    private static function currentUserId(): int
    {
        global $USER;
        if (is_object($USER) && method_exists($USER, 'GetID')) {
            return (int) $USER->GetID();
        }
        return 0;
    }

    private static function log(string $msg): void
    {
        if (function_exists('AddMessage2Log')) {
            AddMessage2Log('[A7NehaCommunityLeads] ' . $msg, 'a7.neha.community');
        }
    }
}

A7NehaCommunityLeads::register();
