#!/usr/bin/env python3
from pathlib import Path

init = Path("/home/bitrix/www/bitrix/php_interface/init.php")
text = init.read_text(encoding="utf-8", errors="replace")
text2 = text.replace("/bitrix/js/a7_renewals_call.js.DISABLED", "/bitrix/js/a7_renewals_call.js")
text2 = text2.replace("/bitrix/js/a7_owner_data_call.js.DISABLED", "/bitrix/js/a7_owner_data_call.js")
init.write_text(text2, encoding="utf-8")
print("re-enabled injects")
print("owner disabled?", "a7_owner_data_call.js.DISABLED" in text2)
print("renewals disabled?", "a7_renewals_call.js.DISABLED" in text2)
