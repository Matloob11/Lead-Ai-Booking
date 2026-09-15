#!/bin/bash
set -euo pipefail
WWW=/home/bitrix/www

echo "=== default outgoing telephony options ==="
php -r '
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$q=$m->query("SELECT MODULE_ID,NAME,VALUE FROM b_option WHERE MODULE_ID IN (\"voximplant\",\"telephony\",\"crm\") AND (NAME LIKE \"%line%\" OR NAME LIKE \"%default%\" OR NAME LIKE \"%portal%\" OR NAME LIKE \"%mode%\" OR NAME LIKE \"%external%\" OR NAME LIKE \"%sip%\" OR NAME LIKE \"%rest%\" OR NAME LIKE \"%number%\") ORDER BY MODULE_ID,NAME");
while($r=$q->fetch_assoc()){echo $r["MODULE_ID"]."\t".$r["NAME"]."\t".substr(str_replace(["\n","\t"],[" "," "],$r["VALUE"]),0,220)."\n";}
'

echo "=== user telephony prefs (sample agents) ==="
php -r '
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$q=$m->query("SELECT USER_ID,CATEGORY,NAME,LEFT(VALUE,120) V FROM b_user_option WHERE CATEGORY IN (\"voximplant\",\"telephony\",\"im\") AND (NAME LIKE \"%line%\" OR NAME LIKE \"%phone%\" OR NAME LIKE \"%default%\" OR NAME LIKE \"%call%\") ORDER BY USER_ID DESC LIMIT 40");
while($r=$q->fetch_assoc()){echo $r["USER_ID"]."\t".$r["CATEGORY"]."\t".$r["NAME"]."\t".$r["V"]."\n";}
'

echo "=== b_voximplant_phone / sip ==="
php -r '
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
foreach(["b_voximplant_phone","b_voximplant_sip","b_voximplant_config","b_voximplant_user","b_voximplant_queue","b_voximplant_line"] as $t){
  $c=$m->query("SHOW TABLES LIKE \"$t\"");
  if(!$c||!$c->num_rows){echo "missing $t\n"; continue;}
  echo "==== $t ====\n";
  $q=$m->query("SELECT * FROM `$t` LIMIT 20");
  while($r=$q->fetch_assoc()){echo json_encode($r,JSON_UNESCAPED_SLASHES)."\n";}
}
'

echo "=== recent voximplant statistic failed reasons ==="
php -r '
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$c=$m->query("SHOW TABLES LIKE \"b_voximplant_statistic\"");
if(!$c||!$c->num_rows){echo "no statistic table\n"; exit;}
$q=$m->query("SELECT ID,CALL_START_DATE,CALL_DURATION,PORTAL_NUMBER,PHONE_NUMBER,CALL_FAILED_CODE,CALL_FAILED_REASON,CALL_STATUS,CALL_TYPE,CALL_VOTE,COMMENT_TEXT FROM b_voximplant_statistic ORDER BY ID DESC LIMIT 25");
while($r=$q->fetch_assoc()){echo json_encode($r,JSON_UNESCAPED_SLASHES)."\n";}
'

echo "=== ONEXTERNAL handlers full URLs ==="
php -r '
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$q=$m->query("SELECT ID,EVENT_NAME,APP_ID,EVENT_HANDLER FROM b_rest_event WHERE EVENT_NAME IN (\"ONEXTERNALCALLSTART\",\"ONEXTERNALCALLBACKSTART\") ORDER BY ID");
while($r=$q->fetch_assoc()){echo $r["ID"]."\t".$r["EVENT_NAME"]."\tapp=".$r["APP_ID"]."\t".$r["EVENT_HANDLER"]."\n";}
$q=$m->query("SELECT ID,CODE,ACTIVE,STATUS,APP_NAME,CLIENT_ID FROM b_rest_app WHERE ID IN (SELECT DISTINCT APP_ID FROM b_rest_event WHERE EVENT_NAME IN (\"ONEXTERNALCALLSTART\",\"ONEXTERNALCALLBACKSTART\"))");
while($r=$q->fetch_assoc()){echo "APP ".$r["ID"]." active=".$r["ACTIVE"]." status=".$r["STATUS"]." code=".$r["CODE"]." name=".$r["APP_NAME"]."\n";}
'

echo "=== zadarma local files ==="
find "$WWW" -iname '*zadarma*' 2>/dev/null | head -40
ls -la "$WWW/bitrix/modules" 2>/dev/null | grep -i zadarma || true
grep -RIl 'zadarma\|OnExternalCallStart\|telephony.externalCall' "$WWW/local" "$WWW/bitrix/php_interface" 2>/dev/null | head -30 || true

echo "=== apache/nginx recent rest/telephony errors ==="
sudo grep -E 'zadarma|ONEXTERNAL|externalCall|voximplant|telephony' /var/log/httpd/error_log /var/log/nginx/error.log /home/bitrix/www/bitrix/modules/*/log* 2>/dev/null | tail -40 || true
ls /home/bitrix/www/bitrix/modules/rest/log 2>/dev/null | tail -5 || true
find /home/bitrix/www/bitrix -name '*rest*event*' -o -name '*event*log*' 2>/dev/null | head -20
