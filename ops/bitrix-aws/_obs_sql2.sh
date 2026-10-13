#!/bin/bash
grep -n "__AfterPrepareSql\|AfterPrepareSql\|fnAfterPrepareSql" -r /home/bitrix/www/bitrix/modules/crm --include='*.php' | head -30
