"""One-off: storageState JSON -> ALOTS_UI_COOKIE env file. Do not print the cookie."""

import json
from pathlib import Path

src = Path("deploy/alots.storage.json")
dst = Path("deploy/.env.alots_ui")
data = json.loads(src.read_text(encoding="utf-8"))
cookies = [c for c in (data.get("cookies") or []) if "alots" in (c.get("domain") or "")]
header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
if "\n" in header or "\r" in header:
    raise SystemExit("refusing a cookie header with newlines")
dst.write_text("ALOTS_UI_COOKIE=\"" + header.replace("\\", "\\\\").replace("\"", "\\\"") + "\"\n", encoding="utf-8")
print(f"cookies {len(cookies)} header_bytes {len(header)}")
