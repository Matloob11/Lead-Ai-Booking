#!/bin/bash
set -euo pipefail
# Extract exact curl block from live handler into /tmp for comparison
sudo php -r '
$path="/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php";
$src=file_get_contents($path);
if (!preg_match("/\\\$ch = curl_init\\(\\\$cfg\\[.url.\\]\\);.*?\\}, 502\\);\\n    \\}/s", $src, $m)) {
  // try line-based
  $lines=explode("\n", $src);
  $start=null; $end=null;
  foreach ($lines as $i=>$line) {
    if (strpos($line, "curl_init(\$cfg['\''url'\''])") !== false) $start=$i;
    if ($start !== null && strpos($line, "Voiso rejected the call") !== false) {
      // find closing of a7_json
    }
  }
  echo "start=".($start===null?"null":$start)."\n";
  if ($start!==null) {
    for ($i=$start; $i<min($start+40, count($lines)); $i++) {
      echo ($i+1).":".json_encode($lines[$i])."\n";
    }
  }
  exit(0);
}
echo "matched\n";
file_put_contents("/tmp/voiso_curl_block.txt", $m[0]);
echo strlen($m[0])."\n";
'
