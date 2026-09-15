#!/usr/bin/env python3
from pathlib import Path

init = Path("/home/bitrix/www/bitrix/php_interface/init.php")
text = init.read_text(encoding="utf-8", errors="replace")
bak = init.with_suffix(".php.before_disable_call")
if not bak.exists():
    bak.write_text(text, encoding="utf-8")

# Soft-disable: inject paths that do not exist so AddHeadScript is harmless
# and browsers stop loading the hangy MutationObserver scripts.
text2 = text.replace("/bitrix/js/a7_renewals_call.js", "/bitrix/js/a7_renewals_call.js.DISABLED")
text2 = text2.replace("/bitrix/js/a7_owner_data_call.js", "/bitrix/js/a7_owner_data_call.js.DISABLED")
init.write_text(text2, encoding="utf-8")
print("disabled custom call injects in init.php")

# Also neutralize live JS immediately (empty stub) in case already cached by browsers with old URL.
for name in ("a7_renewals_call.js", "a7_owner_data_call.js"):
    path = Path("/home/bitrix/www/bitrix/js") / name
    if path.is_file():
        path.write_text(
            "/* temporarily disabled — MutationObserver freeze on CRM kanban */\n",
            encoding="utf-8",
        )
        print("stubbed", path)
