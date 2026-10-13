<?php
/**
 * A7 Portal Lead Fields — on Bayut / Property Finder / Dubizzle lead details:
 * keep useful filled fields where they are, gather empties (+ Call Recording)
 * into one bottom "Other fields" section, hide junk phone UFs, and require the
 * same admin password as stage-create before any new CRM user field is added.
 *
 * Deploy:
 *   /home/bitrix/www/bitrix/php_interface/include/a7_portal_lead_fields.php
 *   /home/bitrix/www/bitrix/js/a7_portal_lead_fields.js
 *   /home/bitrix/www/bitrix/css/a7_portal_lead_fields.css
 * Loaded from init.php.
 */
declare(strict_types=1);

use Bitrix\Main\EventManager;

if (defined('A7_PORTAL_LEAD_FIELDS_LOADED')) {
	return;
}
define('A7_PORTAL_LEAD_FIELDS_LOADED', true);

final class A7PortalLeadFields
{
	public const VERSION = '1.1.0';
	public const PARAM = 'a7_stage_admin_password';
	public const HEADER = 'HTTP_X_A7_STAGE_ADMIN_PASSWORD';
	public const JS_PATH = '/bitrix/js/a7_portal_lead_fields.js';
	public const CSS_PATH = '/bitrix/css/a7_portal_lead_fields.css';

	/** Property Finder / Bayut / Dubizzle SOURCE_IDs */
	public const PORTAL_SOURCES = [
		'UC_KQ0WO3', // Property Finder WhatsApp
		'UC_D83356', // Property Finder Email
		'UC_6R3AM9', // Property Finder Call
		'UC_Y3VNS9', // Bayut WhatsApp
		'UC_4FVN3G', // Bayut Email
		'UC_PCVWT4', // Bayut Call
		'UC_BUIJB2', // Dubizzle WhatsApp
		'UC_LX9888', // Dubizzle Email
		'UC_JPSVQU', // Dubizzle Call
	];

	/** Extra phone UFs — hide on portal lead details (system PHONE stays). */
	public const HIDE_FIELDS = [
		'UF_CRM_1736316526892', // Mobile Number
		'UF_CRM_1733420484604', // Secondary Phone Number
		'UF_CRM_1734247755389', // Phone (Owner Data)
		'UF_CRM_1786771496574', // 971529647138
		'UF_CRM_1786771731997', // New number
		'UF_CRM_LEAD_1736585593011', // My mobile/ WhatsApp number is
		'UF_CRM_1731838225992', // Registered Buyer Phone
		'UF_CRM_1763390140',    // Community (old) — clean Community stays
	];

	/** Always move into the bottom "Other fields" section. */
	public const ALWAYS_OTHER = [
		'UF_CRM_1765536351834', // Call Recording
	];

	/** @var bool|null */
	private static $allowed = null;

	public static function register(): void
	{
		$em = EventManager::getInstance();
		$em->addEventHandler('main', 'OnBeforeProlog', [self::class, 'onBeforeProlog']);
		$em->addEventHandler('main', 'OnProlog', [self::class, 'onProlog']);
		$em->addEventHandler('main', 'OnBeforeUserTypeAdd', [self::class, 'onBeforeUserTypeAdd']);
		$em->addEventHandler('main', 'OnEndBufferContent', [self::class, 'onEndBufferContent']);
	}

	public static function onBeforeUserTypeAdd(&$arFields)
	{
		try {
			if (!is_array($arFields)) {
				return true;
			}
			$entityId = (string)($arFields['ENTITY_ID'] ?? '');
			if ($entityId === '' || !str_starts_with($entityId, 'CRM_')) {
				return true;
			}
			if (self::verifyPassword()) {
				return true;
			}
			$provided = self::passwordFromRequest() !== '';
			global $APPLICATION;
			if (is_object($APPLICATION) && method_exists($APPLICATION, 'ThrowException')) {
				$APPLICATION->ThrowException(self::denyMessage($provided));
			}
			return false;
		} catch (\Throwable $e) {
			return false;
		}
	}

	public static function onBeforeProlog(): void
	{
		try {
			if (self::isBypassContext()) {
				return;
			}
			if (!self::isUserFieldCreateRequest()) {
				return;
			}
			if (self::verifyPassword()) {
				return;
			}
			$provided = self::passwordFromRequest() !== '';
			self::abortJson(self::denyMessage($provided));
		} catch (\Throwable $e) {
			// never break the portal
		}
	}

	public static function onProlog(): void
	{
		try {
			global $APPLICATION, $USER;
			if (!is_object($USER) || !$USER->IsAuthorized()) {
				return;
			}
			if (!self::wantsPageJs()) {
				return;
			}
			self::injectAssets();
		} catch (\Throwable $e) {
			// ignore
		}
	}

	public static function onEndBufferContent(&$content): void
	{
		try {
			if (PHP_SAPI === 'cli' || !is_string($content) || $content === '' || !self::wantsPageJs()) {
				return;
			}
			if (stripos($content, 'a7_portal_lead_fields.js') !== false) {
				return;
			}
			$pos = strripos($content, '</body>');
			if ($pos === false) {
				return;
			}
			$boot = self::bootPayload();
			if ($boot === null) {
				return;
			}
			$jsFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
			$cssFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::CSS_PATH;
			$jsV = is_readable($jsFile) ? (string)@filemtime($jsFile) : (string)time();
			$cssV = is_readable($cssFile) ? (string)@filemtime($cssFile) : (string)time();
			$tag = '<link rel="stylesheet" href="' . self::CSS_PATH . '?v=' . $cssV . '">'
				. '<script>window.A7_PORTAL_LEAD_FIELDS=' . json_encode($boot, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . ';</script>'
				. '<script src="' . self::JS_PATH . '?v=' . $jsV . '"></script>';
			$content = substr($content, 0, $pos) . $tag . "\n" . substr($content, $pos);
		} catch (\Throwable $e) {
		}
	}

	/** @return array<string,mixed>|null */
	public static function bootPayload(): ?array
	{
		$leadId = self::leadIdFromRequest();
		if ($leadId <= 0) {
			return [
				'ok' => true,
				'version' => self::VERSION,
				'leadId' => 0,
				'isPortal' => false,
				'lockCreate' => true,
				'param' => self::PARAM,
				'title' => 'Admin password required',
				'text' => 'Enter admin password to create a new field:',
				'hideFields' => self::HIDE_FIELDS,
				'alwaysOther' => self::ALWAYS_OTHER,
				'portalSources' => self::PORTAL_SOURCES,
			];
		}

		$sourceId = self::leadSourceId($leadId);
		$isPortal = $sourceId !== '' && in_array($sourceId, self::PORTAL_SOURCES, true);

		return [
			'ok' => true,
			'version' => self::VERSION,
			'leadId' => $leadId,
			'sourceId' => $sourceId,
			'isPortal' => $isPortal,
			'lockCreate' => true,
			'param' => self::PARAM,
			'title' => 'Admin password required',
			'text' => 'Enter admin password to create a new field:',
			'hideFields' => self::HIDE_FIELDS,
			'alwaysOther' => self::ALWAYS_OTHER,
			'portalSources' => self::PORTAL_SOURCES,
			'otherTitle' => 'Other fields',
		];
	}

	public static function passwordFromRequest(): string
	{
		$pwd = '';
		if (isset($_REQUEST[self::PARAM]) && is_string($_REQUEST[self::PARAM])) {
			$pwd = (string)$_REQUEST[self::PARAM];
		}
		if ($pwd === '' && isset($_POST[self::PARAM]) && is_string($_POST[self::PARAM])) {
			$pwd = (string)$_POST[self::PARAM];
		}
		if ($pwd === '' && !empty($_SERVER[self::HEADER]) && is_string($_SERVER[self::HEADER])) {
			$pwd = (string)$_SERVER[self::HEADER];
		}
		if ($pwd === '' && !empty($_SERVER['REDIRECT_HTTP_X_A7_STAGE_ADMIN_PASSWORD'])) {
			$pwd = (string)$_SERVER['REDIRECT_HTTP_X_A7_STAGE_ADMIN_PASSWORD'];
		}
		return $pwd;
	}

	public static function verifyPassword(?string $password = null): bool
	{
		if (self::$allowed === true) {
			return true;
		}
		$pwd = $password ?? self::passwordFromRequest();
		if ($pwd === '' && self::isBypassContext()) {
			self::$allowed = true;
			return true;
		}
		if ($pwd === '') {
			return false;
		}
		$hash = self::passwordHash();
		if ($hash === '' || str_contains($hash, 'PLACEHOLDER')) {
			return false;
		}
		$ok = password_verify($pwd, $hash);
		if ($ok) {
			self::$allowed = true;
		}
		return $ok;
	}

	public static function denyMessage(bool $wrong = false): string
	{
		if ($wrong) {
			return 'Incorrect admin password. New field was not created.';
		}
		return 'Admin password required to create a new field.';
	}

	public static function isBypassContext(): bool
	{
		if (defined('A7_PORTAL_LEAD_FIELDS_BYPASS') && A7_PORTAL_LEAD_FIELDS_BYPASS) {
			return true;
		}
		if (PHP_SAPI === 'cli' || PHP_SAPI === 'phpdbg') {
			return true;
		}
		if (defined('BX_CRONTAB') && BX_CRONTAB) {
			return true;
		}
		return false;
	}

	private static function passwordHash(): string
	{
		$path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_stage_admin.config.php';
		$cfg = is_file($path) ? include $path : [];
		if (!is_array($cfg)) {
			return '';
		}
		return (string)($cfg['password_hash'] ?? '');
	}

	private static function wantsPageJs(): bool
	{
		global $USER;
		if (!is_object($USER) || !$USER->IsAuthorized()) {
			return false;
		}
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		return (bool)preg_match('#/crm/lead/(?:details/|type/1/)#i', $uri)
			|| (bool)preg_match('#/crm/type/1/(?:details/|kanban|list)#i', $uri)
			|| str_contains($uri, '/crm/lead/');
	}

	private static function injectAssets(): void
	{
		global $APPLICATION;
		if (!is_object($APPLICATION)) {
			return;
		}
		$boot = self::bootPayload();
		if ($boot === null) {
			return;
		}
		$jsFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
		$cssFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::CSS_PATH;
		$jsV = is_readable($jsFile) ? (string)@filemtime($jsFile) : (string)time();
		$cssV = is_readable($cssFile) ? (string)@filemtime($cssFile) : (string)time();
		if (method_exists($APPLICATION, 'SetAdditionalCSS')) {
			$APPLICATION->SetAdditionalCSS(self::CSS_PATH . '?v=' . $cssV);
		}
		if (method_exists($APPLICATION, 'AddHeadString')) {
			$APPLICATION->AddHeadString(
				'<script>window.A7_PORTAL_LEAD_FIELDS=' . json_encode($boot, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . ';</script>',
				true
			);
		}
		if (method_exists($APPLICATION, 'AddHeadScript')) {
			$APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . $jsV);
		}
	}

	private static function leadIdFromRequest(): int
	{
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		if (preg_match('#/crm/lead/details/(\d+)#i', $uri, $m)) {
			return (int)$m[1];
		}
		if (preg_match('#/crm/type/1/details/(\d+)#i', $uri, $m)) {
			return (int)$m[1];
		}
		$id = (int)($_REQUEST['entityId'] ?? $_REQUEST['entity_id'] ?? $_REQUEST['ID'] ?? 0);
		$type = strtoupper((string)($_REQUEST['entityTypeName'] ?? $_REQUEST['entityType'] ?? 'LEAD'));
		if ($id > 0 && ($type === 'LEAD' || $type === '1')) {
			return $id;
		}
		return 0;
	}

	private static function leadSourceId(int $leadId): string
	{
		if ($leadId <= 0 || !\Bitrix\Main\Loader::includeModule('crm')) {
			return '';
		}
		try {
			$row = \CCrmLead::GetListEx(
				[],
				['=ID' => $leadId, 'CHECK_PERMISSIONS' => 'N'],
				false,
				['nTopCount' => 1],
				['ID', 'SOURCE_ID']
			);
			if ($row && ($ar = $row->Fetch())) {
				return (string)($ar['SOURCE_ID'] ?? '');
			}
		} catch (\Throwable $e) {
		}
		return '';
	}

	private static function isUserFieldCreateRequest(): bool
	{
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		$script = (string)($_SERVER['SCRIPT_NAME'] ?? '');
		$hay = strtolower($script . ' ' . $uri);
		$method = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
		if ($method !== 'POST') {
			return false;
		}

		// BX.ajax.runAction('main.userfieldconfig.add', …)
		$action = strtolower((string)($_REQUEST['action'] ?? $_POST['action'] ?? ''));
		if ($action === '' && preg_match('/[?&]action=([^&]+)/i', $uri, $m)) {
			$action = strtolower(urldecode($m[1]));
		}
		if (
			str_contains($action, 'userfieldconfig.add')
			|| str_contains($action, 'userfield.add')
			|| str_contains($action, 'user.type.add')
		) {
			return self::requestTargetsCrmEntity();
		}

		if (str_contains($hay, 'userfieldconfig') && str_contains($hay, 'add')) {
			return self::requestTargetsCrmEntity();
		}

		// Legacy admin user-field form
		if (str_contains($hay, 'userfield_edit') || str_contains($hay, 'user_field_edit')) {
			return self::requestTargetsCrmEntity();
		}

		return false;
	}

	private static function requestTargetsCrmEntity(): bool
	{
		$entity = '';
		if (isset($_REQUEST['ENTITY_ID']) && is_string($_REQUEST['ENTITY_ID'])) {
			$entity = (string)$_REQUEST['ENTITY_ID'];
		} elseif (isset($_POST['ENTITY_ID']) && is_string($_POST['ENTITY_ID'])) {
			$entity = (string)$_POST['ENTITY_ID'];
		} elseif (isset($_REQUEST['field']) && is_array($_REQUEST['field']) && isset($_REQUEST['field']['ENTITY_ID'])) {
			$entity = (string)$_REQUEST['field']['ENTITY_ID'];
		} elseif (isset($_POST['field']) && is_array($_POST['field']) && isset($_POST['field']['ENTITY_ID'])) {
			$entity = (string)$_POST['field']['ENTITY_ID'];
		}
		if ($entity === '') {
			// Controller payloads vary; OnBeforeUserTypeAdd still enforces.
			return true;
		}
		return str_starts_with(strtoupper($entity), 'CRM_');
	}

	private static function abortJson(string $message): void
	{
		while (ob_get_level() > 0) {
			ob_end_clean();
		}
		header('Content-Type: application/json; charset=UTF-8');
		http_response_code(200);
		echo json_encode([
			'ERROR' => $message,
			'error' => $message,
			'status' => 'error',
			'errors' => [['message' => $message]],
			'a7_portal_lead_fields' => true,
		], JSON_UNESCAPED_UNICODE);
		die();
	}
}

if (class_exists(EventManager::class)) {
	A7PortalLeadFields::register();
}
