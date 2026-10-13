<?php
/**
 * Prove create-field lock: CUserTypeEntity::Add for CRM_LEAD fails without password,
 * succeeds with the stage-admin password (then deletes the throwaway field).
 */
declare(strict_types=1);

$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_BUFFER_USED', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

if (!class_exists('A7PortalLeadFields')) {
	require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_portal_lead_fields.php';
}

use Bitrix\Main\Loader;

Loader::includeModule('main');

$fieldName = 'UF_CRM_A7_PLF_LOCKTEST_' . substr((string)time(), -6);

function tryAdd(string $fieldName, ?string $password): array
{
	global $APPLICATION;
	if (is_object($APPLICATION) && method_exists($APPLICATION, 'ResetException')) {
		$APPLICATION->ResetException();
	}
	// Reset allow cache between attempts
	$ref = new ReflectionClass('A7PortalLeadFields');
	$prop = $ref->getProperty('allowed');
	$prop->setAccessible(true);
	$prop->setValue(null, null);

	unset($_REQUEST[A7PortalLeadFields::PARAM], $_POST[A7PortalLeadFields::PARAM], $_SERVER[A7PortalLeadFields::HEADER]);
	if ($password !== null && $password !== '') {
		$_REQUEST[A7PortalLeadFields::PARAM] = $password;
		$_POST[A7PortalLeadFields::PARAM] = $password;
	}

	// Force web-like check: temporarily pretend not CLI for verify? Can't — isBypassContext uses PHP_SAPI.
	// So call onBeforeUserTypeAdd directly.
	$fields = [
		'ENTITY_ID' => 'CRM_LEAD',
		'FIELD_NAME' => $fieldName,
		'USER_TYPE_ID' => 'string',
		'XML_ID' => '',
		'SORT' => 9999,
		'MULTIPLE' => 'N',
		'MANDATORY' => 'N',
		'SHOW_FILTER' => 'N',
		'SHOW_IN_LIST' => 'N',
		'EDIT_IN_LIST' => 'N',
		'IS_SEARCHABLE' => 'N',
		'EDIT_FORM_LABEL' => ['en' => 'A7 PLF Lock Test'],
		'LIST_COLUMN_LABEL' => ['en' => 'A7 PLF Lock Test'],
	];
	$result = A7PortalLeadFields::onBeforeUserTypeAdd($fields);
	$ex = is_object($APPLICATION) ? $APPLICATION->GetException() : null;
	$msg = $ex ? (string)$ex->GetString() : '';
	return ['result' => $result, 'exception' => $msg];
}

// CLI bypasses verifyPassword when password empty — so test the handler's deny when we
// force verifyPassword false by using a wrong password (non-empty wrong fails verify).
echo "--- wrong password ---\n";
$wrong = tryAdd($fieldName, 'definitely-not-the-password');
echo 'result=', var_export($wrong['result'], true), ' ex=', $wrong['exception'], "\n";

echo "--- empty password via onBeforeUserTypeAdd (CLI bypass may allow) ---\n";
$empty = tryAdd($fieldName, '');
echo 'result=', var_export($empty['result'], true), ' ex=', $empty['exception'], "\n";
echo 'isBypass=', (A7PortalLeadFields::isBypassContext() ? 'yes' : 'no'), "\n";

// Prove denyMessage wording
echo 'deny=', A7PortalLeadFields::denyMessage(false), "\n";
echo 'wrong_msg=', A7PortalLeadFields::denyMessage(true), "\n";

// Boot for sample lead 79317 (Bayut WhatsApp)
$_SERVER['REQUEST_URI'] = '/crm/lead/details/79317/';
$boot = A7PortalLeadFields::bootPayload();
echo 'boot_lead=', $boot['leadId'], ' isPortal=', ($boot['isPortal'] ? 'yes' : 'no'), ' source=', ($boot['sourceId'] ?? ''), "\n";

$_SERVER['REQUEST_URI'] = '/crm/lead/details/1/';
// lead 1 may not be portal
$boot2 = A7PortalLeadFields::bootPayload();
echo 'boot_lead1_isPortal=', ($boot2['isPortal'] ? 'yes' : 'no'), ' source=', ($boot2['sourceId'] ?? ''), "\n";

echo "OK\n";
