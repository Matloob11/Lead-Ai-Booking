<?php
/**
 * A7 observer filter — "All agents" in the Leads Observers picker.
 *
 * Admin (group 1): every lead that has at least one observer.
 * Agent: same observer match, plus ASSIGNED_BY_ID locked to self.
 *
 * Bitrix stores entity-selector values as JSON ["user","21"]. The fake
 * token becomes ["user","all-agents"], which (int) casts to 0 and
 * prepareObserversFieldFilter then drops the SQL — showing every lead.
 * We rewrite OBSERVER_IDS to real observer user ids on the kanban
 * prepareFilter hook (after Bitrix's own transformer).
 */
declare(strict_types=1);

use Bitrix\Main\Application;
use Bitrix\Main\DI\ServiceLocator;
use Bitrix\Main\EventManager;
use Bitrix\Main\Loader;

if (defined('A7_OBSERVER_FILTER_LOADED')) {
    return;
}
define('A7_OBSERVER_FILTER_LOADED', true);

final class A7ObserverFilter
{
    public const VERSION = '1.3.1';
    public const TOKEN = 'all-agents';
    public const TOKEN_SHARED = 'shared-leads';
    public const LABEL_SHARED = 'Shared leads';
    public const JS_PATH = '/bitrix/js/a7_observer_filter.js';
    public const GRID_ID = 'CRM_LEAD_LIST_V12';
    public const SHARE_TABLE = 'a7_lead_share';

    /** @var int[]|null */
    private static $observerUserIds = null;

    public static function register(): void
    {
        self::installListBuilderAutoload();
        $em = EventManager::getInstance();
        $em->addEventHandler('main', 'OnProlog', [self::class, 'onProlog']);
        $em->addEventHandler('main', 'OnBeforeProlog', [self::class, 'onBeforeProlog']);
        $em->addEventHandler('main', 'OnPageStart', [self::class, 'onBeforeProlog']);
    }

    public static function onProlog(): void
    {
        try {
            global $APPLICATION, $USER;
            if (!is_object($USER) || !$USER->IsAuthorized()) {
                return;
            }
            $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
            $wantJs = strpos($uri, '/crm/') === 0
                || strpos($uri, 'crm.kanban') !== false
                || strpos($uri, 'crm.lead') !== false;
            if (!$wantJs) {
                return;
            }
            if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
                return;
            }
            $file = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
            $version = is_readable($file) ? (string)@filemtime($file) : (string)time();
            $APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . $version);
        } catch (\Throwable $e) {
        }
    }

    public static function onBeforeProlog(): void
    {
        try {
            self::rewriteSuperglobals();
            self::installKanbanHook();
        } catch (\Throwable $e) {
        }
    }

    public static function installKanbanHook(): void
    {
        if (!Loader::includeModule('crm')) {
            return;
        }
        if (!class_exists(\Bitrix\Crm\Kanban\Entity\Lead::class, true)) {
            return;
        }
        if (!class_exists('A7KanbanLead', false)) {
            require_once __DIR__ . '/a7_observer_filter_kanban.php';
        }
        ServiceLocator::getInstance()->addInstance('crm.kanban.entity.lead', new A7KanbanLead());
        try {
            $ref = new \ReflectionProperty(\Bitrix\Crm\Kanban\Entity::class, 'instances');
            $ref->setAccessible(true);
            $cur = $ref->getValue();
            if (is_array($cur)) {
                foreach (array_keys($cur) as $key) {
                    if (stripos((string)$key, 'LEAD') === 0) {
                        unset($cur[$key]);
                    }
                }
                $ref->setValue(null, $cur);
            }
        } catch (\Throwable $e) {
        }
    }

    public static function installListBuilderAutoload(): void
    {
        if (class_exists('CCrmEntityListBuilder', false)) {
            return;
        }
        spl_autoload_register([self::class, 'autoloadListBuilder'], true, true);
    }

    public static function autoloadListBuilder(string $class): void
    {
        if ($class !== 'CCrmEntityListBuilder' && strcasecmp($class, 'CCrmEntityListBuilder') !== 0) {
            return;
        }
        $root = (string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www');
        $orig = $root . '/bitrix/modules/crm/classes/general/crm_entity_list_builder.php';
        if (!is_readable($orig)) {
            return;
        }
        $src = (string)file_get_contents($orig);
        $needle = '$arUserSql = call_user_func_array($this->afterPrepareSqlCallback, array($this, $arOrder, $arFilter, $arGroupBy, $arSelectFields));';
        $repl = 'if (is_array($this->afterPrepareSqlCallback) && ($this->afterPrepareSqlCallback[0] ?? "") === "CCrmLead") { \A7ObserverFilter::applyToCrmFilter($arFilter); } $arUserSql = call_user_func_array($this->afterPrepareSqlCallback, array($this, $arOrder, $arFilter, $arGroupBy, $arSelectFields)); if (is_array($this->afterPrepareSqlCallback) && ($this->afterPrepareSqlCallback[0] ?? "") === "CCrmLead") { $arUserSql = \A7ObserverFilter::mergeAfterSql($arUserSql, $arFilter, $this); }';
        if (strpos($src, $needle) !== false) {
            $src = str_replace($needle, $repl, $src);
        }
        // Rent / Sale: expand the "Rent & Sale" filter choice at the top of
        // Prepare(), before UF filters are pulled out and prepared (~line 314),
        // so the list, kanban counts, GetListEx and REST all see Rent OR Sale.
        // Whitespace-tolerant; if the core text ever changes it simply does not
        // inject, and the observer patch above is unaffected.
        $src = preg_replace_callback(
            '/(if\s*\(\s*!is_array\(\$arFilter\)\s*\)\s*\{\s*\$arFilter\s*=\s*array\(\)\s*;\s*\})/',
            static function ($m) {
                return $m[1] . ' if (class_exists(\'\A7RentSale\', false)) { \A7RentSale::applyToCrmFilter($arFilter); }';
            },
            $src,
            1
        );
        eval('?>' . $src);
    }

    /**
     * Mutate a CRM GetList filter for All agents and/or Shared leads.
     */
    public static function applyToCrmFilter(array &$filter): void
    {
        if (class_exists('A7RentSale', false)) {
            A7RentSale::applyToCrmFilter($filter);
        }
        $wantShared = self::shouldShare($filter);
        $wantAll = self::shouldExpand($filter);
        if (!$wantShared && !$wantAll) {
            return;
        }
        if ($wantShared) {
            $leadIds = self::sharedLeadIds();
            $filter['__A7_SHARED_IDS'] = $leadIds ?: [0];
            unset($filter['ID'], $filter['@ID'], $filter['=ID']);
            if (!$wantAll && !self::filterHasConcreteObserver($filter)) {
                unset($filter['OBSERVER_IDS'], $filter['=OBSERVER_IDS']);
            }
        }
        if ($wantAll) {
            $ids = self::observerUserIds();
            $filter['OBSERVER_IDS'] = $ids ?: [0];
            unset($filter['=OBSERVER_IDS']);
            self::lockAssigneeIfAgent($filter);
        }
    }

    /**
     * Extra WHERE for Shared leads. $arFilter ID/@ID is ignored by lead GetListEx.
     *
     * @param array|false $arUserSql
     * @param mixed $sender
     * @return array|false
     */
    public static function mergeAfterSql($arUserSql, array $filter, $sender)
    {
        $ids = $filter['__A7_SHARED_IDS'] ?? null;
        if (!is_array($ids)) {
            return $arUserSql;
        }
        $ids = array_values(array_unique(array_filter(array_map('intval', $ids), static function ($n) {
            return $n > 0;
        })));
        if (!$ids) {
            $ids = [0];
        }
        $alias = 'L';
        if (is_object($sender) && method_exists($sender, 'GetTableAlias')) {
            $a = (string)$sender->GetTableAlias();
            if ($a !== '') {
                $alias = $a;
            }
        }
        $where = $alias . '.ID IN (' . implode(',', $ids) . ')';
        if (!is_array($arUserSql)) {
            $arUserSql = [];
        }
        if (!empty($arUserSql['WHERE'])) {
            $arUserSql['WHERE'] .= ' AND ' . $where;
        } else {
            $arUserSql['WHERE'] = $where;
        }
        return $arUserSql;
    }

    public static function rewriteSuperglobals(): void
    {
        foreach ([&$_GET, &$_POST, &$_REQUEST] as &$bag) {
            if (is_array($bag)) {
                self::decodeJsonLeaves($bag);
                self::walk($bag);
            }
        }
        unset($bag);
    }

    private static function shouldExpand(array $filter): bool
    {
        if (self::payloadHasToken($filter)) {
            return true;
        }
        foreach (['OBSERVER_IDS', '=OBSERVER_IDS'] as $key) {
            if (!isset($filter[$key])) {
                continue;
            }
            $vals = (array)$filter[$key];
            if ($vals === []) {
                continue;
            }
            $positive = 0;
            $zeroish = 0;
            foreach ($vals as $v) {
                if (self::isSharedToken($v) || (is_array($v) && self::payloadHasShared($v))) {
                    continue;
                }
                if (self::isToken($v) || (is_array($v) && self::payloadHasToken($v))) {
                    return true;
                }
                $n = self::toUserId($v);
                if ($n > 0) {
                    $positive++;
                } else {
                    $zeroish++;
                }
            }
            if ($positive === 0 && $zeroish > 0 && self::savedOptionsHaveToken() && !self::savedOptionsHaveShared()) {
                return true;
            }
        }
        foreach (['OBSERVER_IDS_label', '=OBSERVER_IDS_label'] as $key) {
            if (isset($filter[$key]) && self::payloadHasToken($filter[$key])) {
                return true;
            }
            if (isset($filter[$key])) {
                foreach ((array)$filter[$key] as $label) {
                    if (strcasecmp(trim((string)$label), 'All agents') === 0) {
                        return true;
                    }
                }
            }
        }
        if (self::savedOptionsHaveToken() && !self::filterHasConcreteObserver($filter)) {
            return true;
        }
        return false;
    }

    private static function filterHasConcreteObserver(array $filter): bool
    {
        foreach (['OBSERVER_IDS', '=OBSERVER_IDS'] as $key) {
            if (!isset($filter[$key])) {
                continue;
            }
            foreach ((array)$filter[$key] as $v) {
                if (self::payloadHasToken($v)) {
                    continue;
                }
                if (self::toUserId($v) > 0) {
                    return true;
                }
            }
        }
        return false;
    }

    private static function shouldShare(array $filter): bool
    {
        if (self::payloadHasShared($filter)) {
            return true;
        }
        foreach (['OBSERVER_IDS_label', '=OBSERVER_IDS_label'] as $key) {
            if (!isset($filter[$key])) {
                continue;
            }
            foreach ((array)$filter[$key] as $label) {
                if (strcasecmp(trim((string)$label), self::LABEL_SHARED) === 0) {
                    return true;
                }
            }
        }
        return self::savedOptionsHaveShared();
    }

    private static function savedFilterFields(): array
    {
        try {
            if (!class_exists(\CUserOptions::class, false) && !class_exists(\CUserOptions::class, true)) {
                return [];
            }
            $val = \CUserOptions::GetOption('main.ui.filter', self::GRID_ID, false);
            return is_array($val) ? $val : [];
        } catch (\Throwable $e) {
            return [];
        }
    }

    private static function savedOptionsHaveShared(): bool
    {
        return self::payloadHasShared(self::savedFilterFields());
    }

    public static function payloadHasShared($node): bool
    {
        if (is_array($node)) {
            foreach ($node as $v) {
                if (self::payloadHasShared($v)) {
                    return true;
                }
            }
            return false;
        }
        return self::isSharedToken($node);
    }

    private static function isSharedToken($v): bool
    {
        if (is_array($v)) {
            return false;
        }
        $s = strtolower(trim((string)$v));
        if ($s === '') {
            return false;
        }
        if (strpos($s, self::TOKEN_SHARED) !== false) {
            return true;
        }
        return strcasecmp(trim((string)$v), self::LABEL_SHARED) === 0;
    }

    /** @return list<int> */
    public static function sharedLeadIds(): array
    {
        $ids = [];
        try {
            $c = Application::getConnection();
            if (!$c->isTableExists(self::SHARE_TABLE)) {
                return [];
            }
            $sql = 'SELECT DISTINCT LEAD_ID FROM ' . self::SHARE_TABLE;
            if (!self::isAdmin()) {
                $uid = self::currentUserId();
                if ($uid <= 0) {
                    return [];
                }
                $sql = 'SELECT DISTINCT LEAD_ID FROM ' . self::SHARE_TABLE . ' WHERE USER_ID = ' . $uid
                    . ' UNION SELECT DISTINCT s.LEAD_ID FROM ' . self::SHARE_TABLE
                    . ' s INNER JOIN b_crm_lead L ON L.ID = s.LEAD_ID WHERE L.ASSIGNED_BY_ID = ' . $uid;
            }
            $rows = $c->query($sql)->fetchAll();
            foreach ($rows as $row) {
                $n = (int)($row['LEAD_ID'] ?? 0);
                if ($n > 0) {
                    $ids[] = $n;
                }
            }
        } catch (\Throwable $e) {
            return [];
        }
        return array_values(array_unique($ids));
    }

    private static function savedOptionsHaveToken(): bool
    {
        return self::payloadHasToken(self::savedFilterFields());
    }

    public static function payloadHasToken($node): bool
    {
        if (is_array($node)) {
            foreach ($node as $v) {
                if (self::payloadHasToken($v)) {
                    return true;
                }
            }
            return false;
        }
        return self::isToken($node);
    }

    private static function decodeJsonLeaves(array &$node): void
    {
        foreach ($node as &$val) {
            if (is_array($val)) {
                self::decodeJsonLeaves($val);
                continue;
            }
            if (!is_string($val) || $val === '' || ($val[0] !== '{' && $val[0] !== '[')) {
                continue;
            }
            $decoded = json_decode($val, true);
            if (is_array($decoded) && self::payloadHasToken($decoded)) {
                self::walk($decoded);
                $val = json_encode($decoded, JSON_UNESCAPED_UNICODE);
            }
        }
        unset($val);
    }

    private static function walk(array &$node): void
    {
        foreach ($node as $key => &$val) {
            if (is_array($val)) {
                $k = (string)$key;
                if ($k === 'OBSERVER_IDS' || $k === '=OBSERVER_IDS' || substr($k, -12) === 'OBSERVER_IDS') {
                    if (self::payloadHasToken($val)) {
                        $val = self::expandToken(is_array($val) ? $val : [$val]);
                        self::lockAssigneeIfAgent($node);
                    }
                }
                self::walk($val);
            } elseif (self::isToken($val) && (string)$key !== '') {
                $k = (string)$key;
                if ($k === 'OBSERVER_IDS' || strpos($k, 'OBSERVER') !== false) {
                    $node[$key] = self::observerUserIds();
                    self::lockAssigneeIfAgent($node);
                }
            }
        }
        unset($val);
    }

    private static function expandToken(array $vals): array
    {
        $kept = [];
        $hit = false;
        foreach ($vals as $v) {
            if (self::isToken($v)) {
                $hit = true;
                continue;
            }
            if (is_array($v)) {
                if (self::payloadHasToken($v)) {
                    $hit = true;
                    $n = self::toUserId($v);
                    if ($n > 0) {
                        $kept[] = $n;
                    }
                    continue;
                }
                $n = self::toUserId($v);
                if ($n > 0) {
                    $kept[] = $n;
                }
                continue;
            }
            $kept[] = self::toUserId($v);
        }
        if (!$hit) {
            return $vals;
        }
        $ids = self::observerUserIds();
        if (!$ids) {
            return [0];
        }
        $kept = array_values(array_filter($kept, static function ($n) {
            return (int)$n > 0;
        }));
        return array_values(array_unique(array_merge($kept, $ids)));
    }

    private static function toUserId($v): int
    {
        if (is_array($v)) {
            if (isset($v[1])) {
                return self::toUserId($v[1]);
            }
            if (isset($v['id'])) {
                return self::toUserId($v['id']);
            }
            return 0;
        }
        $s = trim((string)$v);
        if ($s !== '' && ($s[0] === '[' || $s[0] === '{')) {
            $decoded = json_decode($s, true);
            if (is_array($decoded)) {
                return self::toUserId($decoded);
            }
        }
        if (stripos($s, 'user_') === 0) {
            $s = substr($s, 5);
        }
        return (int)$s;
    }

    private static function isToken($v): bool
    {
        if (is_array($v)) {
            return false;
        }
        $s = strtolower(trim((string)$v));
        if ($s === '') {
            return false;
        }
        if (strpos($s, self::TOKEN) !== false) {
            return true;
        }
        return $s === 'all-users' || $s === 'all_agents' || $s === 'allagents';
    }

    /** @return list<int> */
    public static function observerUserIds(): array
    {
        if (self::$observerUserIds !== null) {
            return self::$observerUserIds;
        }
        $ids = [];
        try {
            $c = Application::getConnection();
            $rows = $c->query('SELECT DISTINCT USER_ID FROM b_crm_observer WHERE ENTITY_TYPE_ID = 1')->fetchAll();
            foreach ($rows as $row) {
                $n = (int)($row['USER_ID'] ?? 0);
                if ($n > 0) {
                    $ids[] = $n;
                }
            }
        } catch (\Throwable $e) {
            $ids = [];
        }
        self::$observerUserIds = $ids;
        return $ids;
    }

    private static function lockAssigneeIfAgent(array &$node): void
    {
        if (self::isAdmin()) {
            return;
        }
        $uid = self::currentUserId();
        if ($uid <= 0) {
            return;
        }
        $node['ASSIGNED_BY_ID'] = $uid;
        $node['=ASSIGNED_BY_ID'] = $uid;
    }

    private static function currentUserId(): int
    {
        global $USER;
        if (is_object($USER) && method_exists($USER, 'GetID')) {
            return (int)$USER->GetID();
        }
        return 0;
    }

    private static function isAdmin(): bool
    {
        global $USER;
        if (is_object($USER) && method_exists($USER, 'IsAdmin') && $USER->IsAdmin()) {
            return true;
        }
        $uid = self::currentUserId();
        if ($uid <= 0) {
            return false;
        }
        $groups = array_map('intval', (array)\CUser::GetUserGroup($uid));
        return in_array(1, $groups, true);
    }
}

A7ObserverFilter::register();
