<?php
/**
 * Leads that sit with Admin Abdul Malik (user 1) stay in New Lead.
 * When the responsible person changes to anyone else while the lead is
 * still in New Lead, the stage becomes Assigned (UC_MJDO60).
 * Later stages are left alone.
 *
 * Deploy: /home/bitrix/www/bitrix/php_interface/include/a7_lead_stage_owner.php
 */
class A7LeadStageOwner
{
    public const HOLD_USER = 1;
    public const NEW_STAGE = 'NEW';
    public const ASSIGNED_STAGE = 'UC_MJDO60';

    public static function register(): void
    {
        AddEventHandler('crm', 'OnBeforeCrmLeadAdd', [self::class, 'onBeforeAdd']);
        AddEventHandler('crm', 'OnBeforeCrmLeadUpdate', [self::class, 'onBeforeUpdate']);
    }

    public static function onBeforeAdd(&$fields): void
    {
        if (!is_array($fields)) {
            return;
        }
        self::apply($fields, null);
    }

    public static function onBeforeUpdate(&$fields): void
    {
        if (!is_array($fields)) {
            return;
        }
        $id = (int)($fields['ID'] ?? 0);
        if ($id <= 0) {
            return;
        }
        $old = self::load($id);
        if ($old === null) {
            return;
        }
        self::apply($fields, $old);
    }

    public static function apply(array &$fields, ?array $old): void
    {
        $owner = array_key_exists('ASSIGNED_BY_ID', $fields)
            ? (int)$fields['ASSIGNED_BY_ID']
            : (int)($old['ASSIGNED_BY_ID'] ?? self::HOLD_USER);
        $oldStatus = (string)($old['STATUS_ID'] ?? self::NEW_STAGE);
        $creating = $old === null;
        $ownerChanging = !$creating
            && array_key_exists('ASSIGNED_BY_ID', $fields)
            && (int)$fields['ASSIGNED_BY_ID'] !== (int)$old['ASSIGNED_BY_ID'];

        if ($creating) {
            if (self::isHold($owner)) {
                $fields['STATUS_ID'] = self::NEW_STAGE;
                return;
            }
            $status = (string)($fields['STATUS_ID'] ?? self::NEW_STAGE);
            if ($status === '' || $status === self::NEW_STAGE) {
                $fields['STATUS_ID'] = self::ASSIGNED_STAGE;
            }
            return;
        }

        if (!$ownerChanging) {
            return;
        }
        if (self::isHold($owner)) {
            if ($oldStatus === self::NEW_STAGE || $oldStatus === self::ASSIGNED_STAGE) {
                $fields['STATUS_ID'] = self::NEW_STAGE;
            }
            return;
        }
        if ($oldStatus === self::NEW_STAGE) {
            $fields['STATUS_ID'] = self::ASSIGNED_STAGE;
        }
    }

    private static function isHold(int $owner): bool
    {
        return $owner === 0 || $owner === self::HOLD_USER;
    }

    private static function load(int $id): ?array
    {
        global $DB;
        if (!is_object($DB)) {
            return null;
        }
        $row = $DB->Query('SELECT ASSIGNED_BY_ID, STATUS_ID FROM b_crm_lead WHERE ID=' . $id)->Fetch();
        return is_array($row) ? $row : null;
    }
}

A7LeadStageOwner::register();
