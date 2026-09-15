#!/bin/bash
sed -n '1,80p' /home/bitrix/www/bitrix/modules/crm/include.php
echo '===='
F=/home/bitrix/www/bitrix/modules/crm/classes/general/crm_perms.php
grep -n "function GetPermType\|SETTINGS\|ATTR\|DEPARTMENT" "$F" | head -50
echo '==== GetPermType ==='
# extract GetPermType function roughly
awk '/function GetPermType/,/^	function |^	public function |^	protected function /{print NR":"$0; if(NR>1 && /^	function |^	public function |^	protected function / && !/GetPermType/) exit}' "$F" | head -80
echo '==== item permissions ==='
ls /home/bitrix/www/bitrix/modules/crm/lib/Service/UserPermissions/
grep -n "canRead\|DEPARTMENT\|attribute" /home/bitrix/www/bitrix/modules/crm/lib/Service/UserPermissions/Item.php 2>/dev/null | head -40
