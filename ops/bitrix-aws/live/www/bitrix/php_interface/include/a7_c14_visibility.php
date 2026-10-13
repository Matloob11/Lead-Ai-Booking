<?php
/**
 * A7 Availability (C14) visibility — agents see only their own cards.
 *
 * Bitrix list/kanban ORs observer IDs into the access query. A leftover
 * observer therefore shows another agent's Availability card (Sapna saw
 * Abdul Mannan's "mykonos 3.2m"). This module:
 *   - strips observers who are not the assignee on category 14 items
 *   - keeps same-user observers, C13 Owner Data, leads, and CRM roles untouched
 */

use Bitrix\Main\Application;
use Bitrix\Main\EventManager;

if (defined('A7_C14_VISIBILITY_LOADED')) {
    return;
}
define('A7_C14_VISIBILITY_LOADED', true);

final class A7C14Visibility
{
    public const TYPE = 1042;
    public const CATEGORY = 14;

    private static bool $busy = false;

    public static function register(): void
    {
        try {
            $em = EventManager::getInstance();
            $em->addEventHandler('crm', 'OnAfterCrmDynamicItemAdd', [__CLASS__, 'onAfterItem']);
            $em->addEventHandler('crm', 'OnAfterCrmDynamicItemUpdate', [__CLASS__, 'onAfterItem']);
            $em->addEventHandler(
                'crm',
                '\Bitrix\Crm\Observer\Entity\ObserverTable::OnAfterAdd',
                [__CLASS__, 'onObserverAdd']
            );
        } catch (\Throwable $e) {
            self::log('register error: ' . $e->getMessage());
        }
    }

    public static function onAfterItem(&$arFields): void
    {
        if (!is_array($arFields)) {
            return;
        }
        $id = (int) ($arFields['ID'] ?? 0);
        if ($id <= 0) {
            return;
        }
        try {
            self::stripForeignObservers($id);
        } catch (\Throwable $e) {
            self::log("onAfterItem $id error: " . $e->getMessage());
        }
    }

    public static function onObserverAdd($event): void
    {
        try {
            if (!is_object($event) || !method_exists($event, 'getParameter')) {
                return;
            }
            $fields = $event->getParameter('fields');
            if (!is_array($fields) || (int) ($fields['ENTITY_TYPE_ID'] ?? 0) !== self::TYPE) {
                return;
            }
            $entityId = (int) ($fields['ENTITY_ID'] ?? 0);
            if ($entityId > 0) {
                self::stripForeignObservers($entityId);
            }
        } catch (\Throwable $e) {
            self::log('onObserverAdd error: ' . $e->getMessage());
        }
    }

    public static function stripForeignObservers(int $itemId): int
    {
        if ($itemId <= 0 || self::$busy) {
            return 0;
        }
        $c = Application::getConnection();
        $item = $c->query(
            'SELECT ID, CATEGORY_ID, ASSIGNED_BY_ID FROM b_crm_dynamic_items_1042 WHERE ID=' . $itemId
        )->fetch();
        if (!$item || (int) $item['CATEGORY_ID'] !== self::CATEGORY) {
            return 0;
        }
        $assigned = (int) $item['ASSIGNED_BY_ID'];
        self::$busy = true;
        try {
            $c->queryExecute(sprintf(
                'DELETE FROM b_crm_observer
                 WHERE ENTITY_TYPE_ID=%d AND ENTITY_ID=%d AND USER_ID<>%d',
                self::TYPE,
                $itemId,
                $assigned
            ));
            return (int) $c->getAffectedRowsCount();
        } finally {
            self::$busy = false;
        }
    }

    /** @return array{removed:int,items:int} */
    public static function backfill(): array
    {
        $c = Application::getConnection();
        $before = $c->query(
            'SELECT COUNT(*) c FROM b_crm_observer o
             JOIN b_crm_dynamic_items_1042 i ON i.ID=o.ENTITY_ID AND i.CATEGORY_ID=' . self::CATEGORY . '
             WHERE o.ENTITY_TYPE_ID=' . self::TYPE . ' AND o.USER_ID<>i.ASSIGNED_BY_ID'
        )->fetch();
        $c->queryExecute(
            'DELETE o FROM b_crm_observer o
             JOIN b_crm_dynamic_items_1042 i ON i.ID=o.ENTITY_ID AND i.CATEGORY_ID=' . self::CATEGORY . '
             WHERE o.ENTITY_TYPE_ID=' . self::TYPE . ' AND o.USER_ID<>i.ASSIGNED_BY_ID'
        );
        $removed = (int) $c->getAffectedRowsCount();
        return [
            'removed' => $removed > 0 ? $removed : (int) ($before['c'] ?? 0),
            'items' => (int) ($before['c'] ?? 0),
        ];
    }

    private static function log(string $msg): void
    {
        if (function_exists('AddMessage2Log')) {
            AddMessage2Log('[A7C14Visibility] ' . $msg, 'a7.c14.visibility');
        }
    }
}

A7C14Visibility::register();
