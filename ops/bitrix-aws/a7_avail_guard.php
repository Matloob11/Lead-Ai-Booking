<?php
/**
 * A7 Availability Guard (C55) — refuse incomplete Owner Data cards in the three
 * quoteable Availability stages (Rent / Sale / Sale-Rent).
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_avail_guard.php
 * Loaded from: bitrix/php_interface/init.php
 *
 * Required before STAGE_ID may be (or stay as, when fields are cleared):
 *   DT1042_14:UC_73SP7H  Rent Availability
 *   DT1042_14:PREPARATION Sale Availability
 *   DT1042_14:UC_G0PCBL   Sale/Rent Availability
 *
 * Fields (SPA 1042 / CRM_5):
 *   bedrooms  UF_CRM_5_1734246780476
 *   unit_type UF_CRM_5_1734246899822
 *   purpose   UF_CRM_5_1734247157896
 *   sell      UF_CRM_5_1734247021855  OR  lease UF_CRM_5_1734247036310
 *   area      UF_CRM_5_1768487008300  OR  loc_name UF_CRM_5_1777563155595
 *   community UF_CRM_A7_AVAIL_COMMUNITY  (C59; label "Community name" —
 *             kanban "Community" is PARENT_ID_1058 → SPA 1058)
 *
 * English message only. Never breaks a page outside try/catch.
 */
declare(strict_types=1);

use Bitrix\Main\Event;
use Bitrix\Main\EventManager;
use Bitrix\Main\EventResult;
use Bitrix\Main\Error;

if (defined('A7_AVAIL_GUARD_LOADED')) {
	return;
}
define('A7_AVAIL_GUARD_LOADED', true);

final class A7AvailGuard
{
	public const VERSION = '1.1.0';
	public const TYPE = 1042;
	public const CATEGORY = 14;

	public const STAGES = [
		'DT1042_14:UC_73SP7H' => 'Rent Availability',
		'DT1042_14:PREPARATION' => 'Sale Availability',
		'DT1042_14:UC_G0PCBL' => 'Sale/Rent Availability',
	];

	public const F_BEDROOMS = 'UF_CRM_5_1734246780476';
	public const F_UNIT_TYPE = 'UF_CRM_5_1734246899822';
	public const F_PURPOSE = 'UF_CRM_5_1734247157896';
	public const F_SELL = 'UF_CRM_5_1734247021855';
	public const F_LEASE = 'UF_CRM_5_1734247036310';
	public const F_AREA = 'UF_CRM_5_1768487008300';
	public const F_LOC = 'UF_CRM_5_1777563155595';
	public const F_COMMUNITY = 'UF_CRM_A7_AVAIL_COMMUNITY';

	/** REST / Item camelCase spellings of the same fields. */
	private const CAMEL = [
		'ufCrm5_1734246780476' => self::F_BEDROOMS,
		'ufCrm5_1734246899822' => self::F_UNIT_TYPE,
		'ufCrm5_1734247157896' => self::F_PURPOSE,
		'ufCrm5_1734247021855' => self::F_SELL,
		'ufCrm5_1734247036310' => self::F_LEASE,
		'ufCrm5_1768487008300' => self::F_AREA,
		'ufCrm5_1777563155595' => self::F_LOC,
		'ufCrmA7AvailCommunity' => self::F_COMMUNITY,
		'stageId' => 'STAGE_ID',
		'categoryId' => 'CATEGORY_ID',
		'id' => 'ID',
	];

	public static function register(): void
	{
		try {
			$em = EventManager::getInstance();
			$em->addEventHandler('crm', 'onBeforeCrmDynamicItemAdd', [self::class, 'onBeforeItemEvent']);
			$em->addEventHandler('crm', 'onBeforeCrmDynamicItemUpdate', [self::class, 'onBeforeItemEvent']);
			// Legacy spelling used by some builds.
			$em->addEventHandler('crm', 'OnBeforeCrmDynamicItemAdd', [self::class, 'onBeforeItemFields']);
			$em->addEventHandler('crm', 'OnBeforeCrmDynamicItemUpdate', [self::class, 'onBeforeItemFields']);
		} catch (\Throwable $e) {
			self::log('register error: ' . $e->getMessage());
		}
	}

	/** Modern Item event: Event with parameter `item`. */
	public static function onBeforeItemEvent(Event $event): ?EventResult
	{
		try {
			// One-off CLI apply (C56/C57) defines this before prolog so partial fills are not refused.
			if (defined('A7_AVAIL_GUARD_BYPASS') && A7_AVAIL_GUARD_BYPASS) {
				return null;
			}
			$item = $event->getParameter('item');
			if (!is_object($item) || !method_exists($item, 'getEntityTypeId')) {
				return null;
			}
			if ((int)$item->getEntityTypeId() !== self::TYPE) {
				return null;
			}
			$fields = self::fieldsFromItem($item);
			$missing = self::missingForStage($fields);
			if ($missing === []) {
				return null;
			}
			$result = new EventResult(EventResult::ERROR);
			$result->addError(new Error(self::message($missing, (string)($fields['STAGE_ID'] ?? ''))));
			self::log('BLOCK item id=' . (int)($fields['ID'] ?? 0) . ' missing=' . implode(',', $missing));
			return $result;
		} catch (\Throwable $e) {
			self::log('onBeforeItemEvent error: ' . $e->getMessage());
			return null;
		}
	}

	/** Legacy &$arFields handler. Return false to cancel. */
	public static function onBeforeItemFields(&$arFields)
	{
		global $APPLICATION;
		try {
			if (defined('A7_AVAIL_GUARD_BYPASS') && A7_AVAIL_GUARD_BYPASS) {
				return true;
			}
			if (!is_array($arFields)) {
				return true;
			}
			$fields = self::normalise($arFields);
			$typeId = (int)($fields['ENTITY_TYPE_ID'] ?? $arFields['ENTITY_TYPE_ID'] ?? 0);
			if ($typeId && $typeId !== self::TYPE) {
				return true;
			}
			// Some callers omit ENTITY_TYPE_ID; only act when STAGE or category points at 1042/14.
			if (!$typeId && !self::looksLikeOwnerData($fields, $arFields)) {
				return true;
			}
			$id = (int)($fields['ID'] ?? 0);
			if ($id > 0) {
				$fields = self::mergeStored($id, $fields);
			}
			$missing = self::missingForStage($fields);
			if ($missing === []) {
				return true;
			}
			$msg = self::message($missing, (string)($fields['STAGE_ID'] ?? ''));
			self::log('BLOCK fields id=' . $id . ' missing=' . implode(',', $missing));
			if (is_object($APPLICATION) && method_exists($APPLICATION, 'ThrowException')) {
				$APPLICATION->ThrowException($msg, 'A7_AVAIL_REQUIRED');
			}
			return false;
		} catch (\Throwable $e) {
			self::log('onBeforeItemFields error: ' . $e->getMessage());
			return true;
		}
	}

	/** @return list<string> */
	public static function missingForStage(array $fields): array
	{
		$stage = (string)($fields['STAGE_ID'] ?? '');
		if (!isset(self::STAGES[$stage])) {
			return [];
		}
		$category = $fields['CATEGORY_ID'] ?? null;
		if ($category !== null && $category !== '' && (int)$category !== self::CATEGORY) {
			return [];
		}

		$missing = [];
		if (!self::filledEnum($fields[self::F_BEDROOMS] ?? null)) {
			$missing[] = 'No. of Bedroom';
		}
		if (!self::filledEnum($fields[self::F_UNIT_TYPE] ?? null)) {
			$missing[] = 'Unit Type';
		}
		if (!self::filledEnum($fields[self::F_PURPOSE] ?? null)) {
			$missing[] = 'Purpose';
		}
		$sell = self::filledPrice($fields[self::F_SELL] ?? null);
		$lease = self::filledPrice($fields[self::F_LEASE] ?? null);
		if (!$sell && !$lease) {
			$missing[] = 'Sell Price or Lease Price';
		}
		$area = self::filledText($fields[self::F_AREA] ?? null);
		$loc = self::filledText($fields[self::F_LOC] ?? null);
		if (!$area && !$loc) {
			$missing[] = 'Area or loc name';
		}
		if (!self::filledEnum($fields[self::F_COMMUNITY] ?? null)) {
			$missing[] = 'Community name';
		}
		return $missing;
	}

	public static function message(array $missing, string $stage): string
	{
		$label = self::STAGES[$stage] ?? 'Availability';
		return 'Cannot move this card to ' . $label
			. ' until these fields are filled: ' . implode(', ', $missing)
			. '. Lead AI only quotes complete Availability cards.';
	}

	/** @return array<string,mixed> */
	private static function fieldsFromItem(object $item): array
	{
		$out = [
			'ID' => method_exists($item, 'getId') ? (int)$item->getId() : 0,
			'ENTITY_TYPE_ID' => (int)$item->getEntityTypeId(),
			'STAGE_ID' => method_exists($item, 'getStageId') ? (string)$item->getStageId() : '',
			'CATEGORY_ID' => method_exists($item, 'getCategoryId') ? (int)$item->getCategoryId() : self::CATEGORY,
		];
		foreach ([
			self::F_BEDROOMS, self::F_UNIT_TYPE, self::F_PURPOSE,
			self::F_SELL, self::F_LEASE, self::F_AREA, self::F_LOC,
			self::F_COMMUNITY,
		] as $uf) {
			$out[$uf] = method_exists($item, 'get') ? $item->get($uf) : null;
		}
		return $out;
	}

	/** @return array<string,mixed> */
	private static function normalise(array $raw): array
	{
		$out = [];
		foreach ($raw as $key => $value) {
			$k = (string)$key;
			if (isset(self::CAMEL[$k])) {
				$out[self::CAMEL[$k]] = $value;
			} else {
				$out[strtoupper($k) === $k ? $k : $k] = $value;
				// Keep UF_ as-is when already uppercase.
				if (str_starts_with($k, 'UF_') || str_starts_with($k, 'ufCrm')) {
					$mapped = self::CAMEL[$k] ?? $k;
					if (str_starts_with($k, 'ufCrm')) {
						$mapped = self::CAMEL[$k] ?? ('UF_CRM_5_' . substr($k, strlen('ufCrm5_')));
					}
					$out[$mapped] = $value;
				}
			}
		}
		if (isset($raw['STAGE_ID'])) {
			$out['STAGE_ID'] = $raw['STAGE_ID'];
		}
		if (isset($raw['CATEGORY_ID'])) {
			$out['CATEGORY_ID'] = $raw['CATEGORY_ID'];
		}
		if (isset($raw['ID'])) {
			$out['ID'] = $raw['ID'];
		}
		return $out;
	}

	private static function looksLikeOwnerData(array $fields, array $raw): bool
	{
		$stage = (string)($fields['STAGE_ID'] ?? $raw['STAGE_ID'] ?? $raw['stageId'] ?? '');
		if (isset(self::STAGES[$stage]) || str_starts_with($stage, 'DT1042_')) {
			return true;
		}
		foreach ($raw as $key => $_) {
			if (is_string($key) && (str_starts_with($key, 'UF_CRM_5_') || str_starts_with($key, 'ufCrm5_'))) {
				return true;
			}
		}
		return false;
	}

	/** @return array<string,mixed> */
	private static function mergeStored(int $id, array $fields): array
	{
		try {
			if (!\Bitrix\Main\Loader::includeModule('crm')) {
				return $fields;
			}
			$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(self::TYPE);
			if (!$factory) {
				return $fields;
			}
			$item = $factory->getItem($id);
			if (!$item) {
				return $fields;
			}
			$stored = self::fieldsFromItem($item);
			foreach ($stored as $k => $v) {
				if (!array_key_exists($k, $fields) || $fields[$k] === null || $fields[$k] === '') {
					$fields[$k] = $v;
				}
			}
			return $fields;
		} catch (\Throwable $e) {
			self::log('mergeStored error: ' . $e->getMessage());
			return $fields;
		}
	}

	private static function filledEnum($value): bool
	{
		if ($value === null || $value === '' || $value === false) {
			return false;
		}
		if (is_array($value)) {
			$value = reset($value);
		}
		return (int)$value > 0;
	}

	private static function filledPrice($value): bool
	{
		if ($value === null || $value === '' || $value === false) {
			return false;
		}
		if (!is_numeric($value)) {
			return false;
		}
		return (float)$value > 0;
	}

	private static function filledText($value): bool
	{
		if ($value === null || $value === false) {
			return false;
		}
		if (is_array($value)) {
			$value = implode(' ', $value);
		}
		return trim((string)$value) !== '';
	}

	private static function log(string $msg): void
	{
		if (function_exists('AddMessage2Log')) {
			AddMessage2Log('[A7AvailGuard] ' . $msg, 'a7.avail.guard');
		}
		@file_put_contents(
			'/home/bitrix/a7_avail_guard.log',
			date('c') . ' ' . $msg . "\n",
			FILE_APPEND | LOCK_EX
		);
	}
}

A7AvailGuard::register();
