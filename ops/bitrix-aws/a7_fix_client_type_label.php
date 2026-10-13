<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$field = 'UF_CRM_1756638760279';
$row = \Bitrix\Main\Application::getConnection()->query(
	"SELECT ID FROM b_user_field WHERE ENTITY_ID='CRM_LEAD' AND FIELD_NAME='" . $field . "'"
)->fetch();
if (!$row) {
	fwrite(STDERR, "field missing\n");
	exit(1);
}
$id = (int)$row['ID'];
$ent = new CUserTypeEntity();
$ok = $ent->Update($id, [
	'EDIT_FORM_LABEL' => ['en' => 'Client Type', 'ru' => 'Client Type'],
	'LIST_COLUMN_LABEL' => ['en' => 'Client Type', 'ru' => 'Client Type'],
	'LIST_FILTER_LABEL' => ['en' => 'Client Type', 'ru' => 'Client Type'],
]);
echo $ok ? "updated Client Type label id=$id\n" : "update failed\n";
$lang = \Bitrix\Main\Application::getConnection()->query(
	"SELECT LANGUAGE_ID, EDIT_FORM_LABEL, LIST_COLUMN_LABEL FROM b_user_field_lang WHERE USER_FIELD_ID=$id"
);
while ($l = $lang->fetch()) {
	echo json_encode($l, JSON_UNESCAPED_UNICODE), "\n";
}
