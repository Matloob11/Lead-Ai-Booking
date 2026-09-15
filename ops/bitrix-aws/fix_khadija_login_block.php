<?php
/**
 * Unblock Bitrix login for khadijafrom7g@gmail.com.
 * Never prints password / hashes / settings secrets.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$email = 'khadijafrom7g@gmail.com';
$apply = getenv('APPLY') === '1';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
	fwrite(STDERR, "db fail\n");
	exit(2);
}

$emailSql = $m->real_escape_string($email);
$q = $m->query(
	"SELECT ID, LOGIN, EMAIL, NAME, LAST_NAME, ACTIVE, BLOCKED,
	        LOGIN_ATTEMPTS, DATE_REGISTER, LAST_LOGIN, LAST_ACTIVITY_DATE
	 FROM b_user
	 WHERE EMAIL='$emailSql' OR LOGIN='$emailSql'
	    OR EMAIL LIKE '%khadijafrom7g%'
	    OR LOGIN LIKE '%khadija%'
	    OR CONCAT(NAME,' ',LAST_NAME) LIKE '%khadija%'
	 ORDER BY ID"
);
$rows = [];
while ($r = $q->fetch_assoc()) {
	$rows[] = $r;
	echo json_encode([
		'id' => $r['ID'],
		'login' => $r['LOGIN'],
		'email' => $r['EMAIL'],
		'name' => trim($r['NAME'] . ' ' . $r['LAST_NAME']),
		'active' => $r['ACTIVE'],
		'blocked' => $r['BLOCKED'],
		'login_attempts' => $r['LOGIN_ATTEMPTS'],
		'last_login' => $r['LAST_LOGIN'],
	], JSON_UNESCAPED_UNICODE) . "\n";
}

if (!$rows) {
	echo "USER_NOT_FOUND\n";
	exit(1);
}

$target = null;
foreach ($rows as $r) {
	if (strcasecmp((string)$r['EMAIL'], $email) === 0 || strcasecmp((string)$r['LOGIN'], $email) === 0) {
		$target = $r;
		break;
	}
}
if (!$target) {
	echo "EMAIL_NOT_EXACT_MATCH\n";
	exit(1);
}

$uid = (int)$target['ID'];
echo "target_id=$uid apply=" . ($apply ? 'yes' : 'no') . "\n";

if (!$apply) {
	echo "DRY_RUN\n";
	exit(0);
}

$fields = [
	'BLOCKED' => 'N',
	'ACTIVE' => 'Y',
	'LOGIN_ATTEMPTS' => 0,
];
$user = new CUser();
$ok = $user->Update($uid, $fields);
echo "update_ok=" . ($ok ? 'yes' : 'no') . "\n";
if (!$ok) {
	$ex = $user->LAST_ERROR ?: ($GLOBALS['APPLICATION']->GetException() ? $GLOBALS['APPLICATION']->GetException()->GetString() : 'unknown');
	echo "update_err=$ex\n";
	exit(1);
}

$again = $m->query(
	"SELECT ID, EMAIL, ACTIVE, BLOCKED, LOGIN_ATTEMPTS FROM b_user WHERE ID=$uid"
)->fetch_assoc();
echo "prove " . json_encode([
	'id' => $again['ID'],
	'email' => $again['EMAIL'],
	'active' => $again['ACTIVE'],
	'blocked' => $again['BLOCKED'],
	'login_attempts' => $again['LOGIN_ATTEMPTS'],
], JSON_UNESCAPED_UNICODE) . "\n";
echo "DONE\n";
