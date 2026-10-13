<?php

/**
 * Recordings Ops Console - Bitrix Left-Menu Placement Frame.
 *
 * Requirements:
 * - Requires an authenticated Bitrix portal administrator.
 * - Non-admins receive HTTP 403 with no operational data or configuration.
 * - Embeds the Hostinger Recordings Ops console in a full-height iframe.
 */

if (!defined('NO_KEEP_STATISTIC')) {
    define('NO_KEEP_STATISTIC', true);
}
if (!defined('NOT_CHECK_PERMISSIONS')) {
    define('NOT_CHECK_PERMISSIONS', true);
}

$documentRoot = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www'), '/');
$prolog = $documentRoot . '/bitrix/modules/main/include/prolog_before.php';
if (is_readable($prolog)) {
    require_once $prolog;
}

global $USER;
if (!is_object($USER)
    || !method_exists($USER, 'IsAuthorized')
    || !$USER->IsAuthorized()
    || !method_exists($USER, 'IsAdmin')
    || !$USER->IsAdmin()
) {
    http_response_code(403);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><html><head><title>Access Denied</title></head>'
        . '<body style="font-family:sans-serif;padding:2rem;">'
        . '<h2>Admins only</h2><p>This console is restricted to Bitrix administrators.</p>'
        . '</body></html>';
    exit;
}

$hostingerOpsUrl = 'https://recordings.srv1802669.hstgr.cloud/';

header('Content-Type: text/html; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recordings Ops</title>
<script src="//api.bitrix24.com/api/v1/"></script>
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #0f141c; }
  iframe { border: 0; width: 100%; height: 100%; display: block; }
</style>
</head>
<body>
<iframe id="ops-frame" src="<?php echo htmlspecialchars($hostingerOpsUrl, ENT_QUOTES, 'UTF-8'); ?>" allow="clipboard-write"></iframe>
<script>
  if (window.BX24) {
    BX24.init(function() {
      var auth = BX24.getAuth();
      var frame = document.getElementById('ops-frame');
      if (auth && frame && frame.contentWindow) {
        frame.contentWindow.postMessage({ type: 'bx24_auth', auth: auth }, '*');
      }
    });
  }
</script>
</body>
</html>
