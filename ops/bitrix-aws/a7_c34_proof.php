<?php
/**
 * C34: prove a failed bot-status POST is retried from the queue and succeeds later.
 * CLI only. Uses the sendHook so no real HTTP is needed. Deletes the test lead.
 *
 * Run: ops/bitrix.sh run a7_c34_proof.php
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_leadai_bot_status.php';

function say(string $line): void
{
    echo $line, "\n";
}

\Bitrix\Main\Loader::includeModule('crm');
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);

$item = $factory->createItem([
    'TITLE' => 'ZZ C34 proof delete',
    'NAME' => 'C34',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'IN_PROCESS',
]);
$add = $factory->getAddOperation($item, $context);
$add->disableCheckAccess();
$add->disableBizProc();
$add->disableAutomation();
$add->launch();
$leadId = (int)$item->getId();
say('LEAD ' . $leadId);

@unlink(A7LeadaiBotStatus::QUEUE);
$calls = 0;
$codes = [];
A7LeadaiBotStatus::$sendHook = static function ($body, $ts, $sign, $url) use (&$calls, &$codes) {
    $calls++;
    // First attempt fails (like unreachable); later attempts succeed.
    $code = $calls === 1 ? 0 : 200;
    $codes[] = $code;
    return $code;
};

// Simulate a person's Handed-to-agent change via the public post path:
// enqueue by forcing a failed first send through reflection of private post.
$ref = new ReflectionClass(A7LeadaiBotStatus::class);
$post = $ref->getMethod('post');
$post->setAccessible(true);
$post->invoke(null, $leadId, 2478, 0);
say('AFTER_FIRST calls=' . $calls . ' codes=' . implode(',', $codes));
say('QUEUE_EXISTS ' . (is_file(A7LeadaiBotStatus::QUEUE) ? 'yes' : 'no'));

// Make the queued row due now.
if (is_file(A7LeadaiBotStatus::QUEUE)) {
    $rows = [];
    foreach (file(A7LeadaiBotStatus::QUEUE) as $line) {
        $itemQ = json_decode(trim($line), true);
        if (is_array($itemQ)) {
            $itemQ['next_at'] = time() - 1;
            $rows[] = $itemQ;
        }
    }
    $out = '';
    foreach ($rows as $row) {
        $out .= json_encode($row, JSON_UNESCAPED_SLASHES) . "\n";
    }
    file_put_contents(A7LeadaiBotStatus::QUEUE, $out);
}

$attempted = A7LeadaiBotStatus::processQueue();
say('RETRY attempted=' . $attempted . ' calls=' . $calls . ' codes=' . implode(',', $codes));
say('QUEUE_AFTER ' . (is_file(A7LeadaiBotStatus::QUEUE) ? 'still' : 'gone'));

$pass = ($calls >= 2 && in_array(0, $codes, true) && in_array(200, $codes, true) && !is_file(A7LeadaiBotStatus::QUEUE));
say('PASS ' . ($pass ? 'yes' : 'no'));

A7LeadaiBotStatus::$sendHook = null;
$del = $factory->getDeleteOperation($factory->getItem($leadId), $context);
$del->disableCheckAccess();
$del->disableBizProc();
$del->disableAutomation();
$del->launch();
say('DELETED ' . ($factory->getItem($leadId) === null ? 'yes' : 'no'));
say('DONE');
