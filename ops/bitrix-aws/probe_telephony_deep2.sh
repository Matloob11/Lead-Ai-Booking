#!/bin/bash
set -eu
WWW=/home/bitrix/www

echo "=== ONEXTERNAL handlers + apps ==="
php <<'PHP'
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$q=$m->query("SELECT e.ID,e.EVENT_NAME,e.APP_ID,e.EVENT_HANDLER,a.CODE,a.ACTIVE,a.STATUS,a.APP_NAME FROM b_rest_event e LEFT JOIN b_rest_app a ON a.ID=e.APP_ID WHERE e.EVENT_NAME IN ('ONEXTERNALCALLSTART','ONEXTERNALCALLBACKSTART') ORDER BY e.ID");
while($r=$q->fetch_assoc()){echo json_encode($r,JSON_UNESCAPED_SLASHES)."\n";}
PHP

echo "=== voximplant options ==="
php <<'PHP'
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$q=$m->query("SELECT MODULE_ID,NAME,LEFT(VALUE,300) V FROM b_option WHERE MODULE_ID IN ('voximplant','telephony','crm','im') AND (NAME LIKE '%line%' OR NAME LIKE '%default%' OR NAME LIKE '%portal%' OR NAME LIKE '%mode%' OR NAME LIKE '%external%' OR NAME LIKE '%sip%' OR NAME LIKE '%rest%' OR NAME LIKE '%number%' OR NAME LIKE '%phone%') ORDER BY MODULE_ID,NAME");
while($r=$q->fetch_assoc()){echo $r["MODULE_ID"]."\t".$r["NAME"]."\t".$r["V"]."\n";}
PHP

echo "=== voximplant tables sample ==="
php <<'PHP'
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$tq=$m->query("SHOW TABLES LIKE 'b_voximplant%'");
while($t=$tq->fetch_row()){
  echo "TABLE ".$t[0]."\n";
  $cnt=$m->query("SELECT COUNT(*) c FROM `{$t[0]}`")->fetch_assoc();
  echo " count=".$cnt["c"]."\n";
  if((int)$cnt["c"]>0 && (int)$cnt["c"]<500){
    $q=$m->query("SELECT * FROM `{$t[0]}` LIMIT 8");
    while($r=$q->fetch_assoc()){echo "  ".json_encode($r,JSON_UNESCAPED_SLASHES)."\n";}
  } elseif((int)$cnt["c"]>=500){
    $q=$m->query("SELECT * FROM `{$t[0]}` ORDER BY 1 DESC LIMIT 5");
    while($r=$q->fetch_assoc()){echo "  ".json_encode($r,JSON_UNESCAPED_SLASHES)."\n";}
  }
}
PHP

echo "=== recent statistic ==="
php <<'PHP'
$s=include "/home/bitrix/www/bitrix/.settings.php";
$db=$s["connections"]["value"]["default"];
$m=new mysqli($db["host"],$db["login"],$db["password"],$db["database"]);
$c=$m->query("SHOW TABLES LIKE 'b_voximplant_statistic'");
if(!$c||!$c->num_rows){echo "no statistic\n"; exit;}
$cols=[]; $q=$m->query("SHOW COLUMNS FROM b_voximplant_statistic"); while($r=$q->fetch_assoc()) $cols[]=$r["Field"];
echo "cols=".implode(",",$cols)."\n";
$q=$m->query("SELECT * FROM b_voximplant_statistic ORDER BY ID DESC LIMIT 20");
while($r=$q->fetch_assoc()){echo json_encode($r,JSON_UNESCAPED_SLASHES)."\n";}
PHP

echo "=== A7_CALL_FEATURES + event path ==="
grep -n "A7_CALL_FEATURES_ENABLED\|externalCall.finish\|function a7_handle_event\|action === 'event'" /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php | head -40

echo "=== rest event send log if any ==="
ls -la /home/bitrix/www/upload/a7_3cx_click_to_call.log 2>/dev/null || true
tail -n 30 /home/bitrix/www/upload/a7_3cx_click_to_call.log 2>/dev/null || true
