"""ALOTS_UI_COOKIE env line -> raw cookie file (Compose-safe). Prints length only."""

from pathlib import Path

src = Path("deploy/.env.alots_ui")
dst = Path("deploy/alots.ui.cookie")
raw = src.read_text(encoding="utf-8").strip()
prefix = "ALOTS_UI_COOKIE="
if not raw.startswith(prefix):
    raise SystemExit("missing ALOTS_UI_COOKIE")
cookie = raw[len(prefix) :].strip()
if cookie.startswith('"') and cookie.endswith('"'):
    cookie = cookie[1:-1].replace('\\"', '"').replace("\\\\", "\\")
if "$" in cookie and "$$" not in cookie:
    pass  # file mount; `$` is fine
dst.write_text(cookie.strip() + "\n", encoding="utf-8")
print("cookie_bytes", len(cookie))
