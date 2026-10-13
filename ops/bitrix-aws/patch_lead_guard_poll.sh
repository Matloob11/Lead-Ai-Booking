#!/bin/bash
set -euo pipefail
JS=/home/bitrix/www/bitrix/js/a7_lead_guard.js
TS=$(date +%Y%m%d_%H%M%S)
cp -a "$JS" "${JS}.bak.${TS}"

# pending poll: 60s -> 180s (every portal tab)
python3 - <<'PY'
from pathlib import Path
p = Path('/home/bitrix/www/bitrix/js/a7_lead_guard.js')
s = p.read_text(encoding='utf-8')
old = s
# global pending poll
s = s.replace(
    "window.setInterval(function () { try { loadPending(); } catch (e) {} }, 60000);",
    "window.setInterval(function () { try { loadPending(); } catch (e) {} }, 180000);",
    1,
)
# lead-page loadInfo poll
s = s.replace(
    """        window.setInterval(function () {
          try { loadInfo(); } catch (e) {}
        }, 60000);""",
    """        window.setInterval(function () {
          try { loadInfo(); } catch (e) {}
        }, 180000);""",
    1,
)
# list cache
s = s.replace(
    """        window.setInterval(function () {
          try { refreshListCache(); } catch (e) {}
        }, 120000);""",
    """        window.setInterval(function () {
          try { refreshListCache(); } catch (e) {}
        }, 300000);""",
    1,
)
if s == old:
    raise SystemExit('no interval replacements made')
p.write_text(s, encoding='utf-8')
print('patched ok')
PY

grep -nE 'setInterval|180000|300000|, 60000|, 120000' "$JS" | head -20
