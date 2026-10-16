<?php
/**
 * Rent / Sale lead tag — one dropdown on leads: Rent | Sale | Rent & Sale.
 *
 * Where the value comes from (both signals, never blanks a manual choice):
 *   Client Type (UF_CRM_1756638760279): Tenant -> Rent, Buyer/Seller -> Sale
 *   Offering Type (UF_CRM_1735126982325): "rent" -> Rent, "sale" -> Sale
 *   both present and disagreeing -> Rent & Sale
 * Kept in sync on OnBeforeCrmLeadAdd / OnBeforeCrmLeadUpdate whenever a source
 * field is part of the write. In the lead filter the choice "Rent & Sale" means
 * every tagged lead (Rent OR Sale OR Rent & Sale); A7ObserverFilter::applyToCrmFilter
 * delegates here so list, kanban, counts and GetListEx all see the expansion.
 *
 * Deploy: /home/bitrix/www/bitrix/php_interface/include/a7_rent_sale.php
 * Setup (creates the field + values, backfills): deploy_rent_sale_setup.php
 */
class A7RentSale
{
    public const FIELD = 'UF_CRM_A7_RENT_SALE';
    public const SRC_CLIENT_TYPE = 'UF_CRM_1756638760279';
    public const SRC_OFFERING = 'UF_CRM_1735126982325';
    public const V_RENT = 'Rent';
    public const V_SALE = 'Sale';
    public const V_BOTH = 'Rent & Sale';

    /** @var array<string,int>|null value label => enum id of our field */
    private static $enum = null;
    /** @var array<int,string>|null enum id => value of the Client Type field */
    private static $clientType = null;

    public static function register(): void
    {
        AddEventHandler('crm', 'OnBeforeCrmLeadAdd', [self::class, 'onBeforeAdd']);
        AddEventHandler('crm', 'OnBeforeCrmLeadUpdate', [self::class, 'onBeforeUpdate']);
    }

    public static function enumIds(): array
    {
        if (self::$enum !== null) {
            return self::$enum;
        }
        self::$enum = [];
        try {
            $c = \Bitrix\Main\Application::getConnection();
            $r = $c->query(
                "SELECT e.ID, e.VALUE FROM b_user_field_enum e
                 JOIN b_user_field f ON f.ID = e.USER_FIELD_ID
                 WHERE f.ENTITY_ID = 'CRM_LEAD' AND f.FIELD_NAME = '" . self::FIELD . "'"
            );
            while ($row = $r->fetch()) {
                self::$enum[trim((string)$row['VALUE'])] = (int)$row['ID'];
            }
        } catch (\Throwable $e) {
        }
        return self::$enum;
    }

    public static function clientTypeValues(): array
    {
        if (self::$clientType !== null) {
            return self::$clientType;
        }
        self::$clientType = [];
        try {
            $c = \Bitrix\Main\Application::getConnection();
            $r = $c->query(
                "SELECT e.ID, e.VALUE FROM b_user_field_enum e
                 JOIN b_user_field f ON f.ID = e.USER_FIELD_ID
                 WHERE f.ENTITY_ID = 'CRM_LEAD' AND f.FIELD_NAME = '" . self::SRC_CLIENT_TYPE . "'"
            );
            while ($row = $r->fetch()) {
                self::$clientType[(int)$row['ID']] = strtolower(trim((string)$row['VALUE']));
            }
        } catch (\Throwable $e) {
        }
        return self::$clientType;
    }

    /** Rent / Sale / Rent & Sale label from the two sources, null when neither says anything. */
    public static function derive($clientTypeEnumId, $offering): ?string
    {
        $rent = false;
        $sale = false;
        if (is_array($clientTypeEnumId)) {
            $clientTypeEnumId = reset($clientTypeEnumId);
        }
        $ct = self::clientTypeValues()[(int)$clientTypeEnumId] ?? '';
        if ($ct === 'tenant') {
            $rent = true;
        } elseif ($ct === 'buyer' || $ct === 'seller') {
            $sale = true;
        }
        $of = strtolower(trim((string)$offering));
        if ($of === 'rent') {
            $rent = true;
        } elseif ($of === 'sale') {
            $sale = true;
        }
        if ($rent && $sale) {
            return self::V_BOTH;
        }
        if ($rent) {
            return self::V_RENT;
        }
        if ($sale) {
            return self::V_SALE;
        }
        return null;
    }

    public static function onBeforeAdd(&$fields): void
    {
        if (is_array($fields)) {
            self::apply($fields, []);
        }
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
        // Only recompute when a source field is part of this write, so an
        // agent's manual Rent/Sale choice survives unrelated edits.
        if (!array_key_exists(self::SRC_CLIENT_TYPE, $fields) && !array_key_exists(self::SRC_OFFERING, $fields)) {
            return;
        }
        self::apply($fields, self::load($id));
    }

    private static function load(int $id): array
    {
        try {
            $c = \Bitrix\Main\Application::getConnection();
            $row = $c->query(
                "SELECT `" . self::SRC_CLIENT_TYPE . "` AS ct, `" . self::SRC_OFFERING . "` AS ofr
                 FROM b_uts_crm_lead WHERE VALUE_ID = " . $id
            )->fetch();
            return is_array($row) ? $row : [];
        } catch (\Throwable $e) {
            return [];
        }
    }

    private static function apply(array &$fields, array $old): void
    {
        $ct = array_key_exists(self::SRC_CLIENT_TYPE, $fields) ? $fields[self::SRC_CLIENT_TYPE] : ($old['ct'] ?? null);
        $of = array_key_exists(self::SRC_OFFERING, $fields) ? $fields[self::SRC_OFFERING] : ($old['ofr'] ?? null);
        // C39: a C6 write that already set Rent/Sale is left as sent.
        if ((int)($GLOBALS['A7_LEADAI_FIELDS_SAVE'] ?? 0) > 0 && array_key_exists(self::FIELD, $fields)) {
            return;
        }
        $label = self::derive($ct, $of);
        if ($label === null) {
            return;
        }
        $enumId = self::enumIds()[$label] ?? 0;
        if ($enumId > 0) {
            $fields[self::FIELD] = $enumId;
        }
    }

    /** Filter choice "Rent & Sale" => Rent OR Sale OR Rent & Sale (all tagged leads). */
    public static function applyToCrmFilter(array &$filter): void
    {
        $ids = self::enumIds();
        $both = (int)($ids[self::V_BOTH] ?? 0);
        if ($both <= 0) {
            return;
        }
        $all = array_values(array_filter([
            (int)($ids[self::V_RENT] ?? 0),
            (int)($ids[self::V_SALE] ?? 0),
            $both,
        ]));
        foreach ($filter as $key => $val) {
            if (!is_string($key) || $key === '' || $key[0] === '!') {
                continue;
            }
            if (ltrim($key, '=<>@%~') !== self::FIELD) {
                continue;
            }
            $vals = array_map('intval', is_array($val) ? $val : [$val]);
            if (in_array($both, $vals, true)) {
                $filter[$key] = array_values(array_unique(array_merge($vals, $all)));
            }
        }
    }
}

A7RentSale::register();
