# Read-only-ish live probe, run through `ops/wa.sh probe-gateway-upload`:
# does the gateway broker Meta's resumable upload with OUR API key (the
# icpaas.in PDF, steps 1+2)? Starts one upload session and uploads a 70-byte
# PNG; no template is created, no message is sent. Never prints the key.
import base64
import json

import httpx
from django.conf import settings

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
key = (getattr(settings, "ALOTS_API_KEY", "") or "").strip()
ver = (getattr(settings, "ALOTS_VERSION", "") or "v23.0").strip("/")
base_cfg = (getattr(settings, "ALOTS_BASE_URL", "") or "https://alots.io").rstrip("/")
hosts = [base_cfg] + ([] if "icpaas.in" in base_cfg else ["https://icpaas.in"])
print("api key set:", "yes" if key else "no", "| version:", ver, "| configured base:", base_cfg)
H = {"Authorization": f"Bearer {key}", "Version": ver}
for base in hosts:
    print("== host:", base)
    try:
        with httpx.Client(timeout=40) as c:
            r1 = c.post(f"{base}/{ver}/app/uploads", headers=H,
                        data={"file_length": str(len(PNG)), "file_type": "image/png", "file_name": "a7_probe.png"})
            ct = r1.headers.get("content-type", "")
            print("  step1 POST /app/uploads ->", r1.status_code, ct[:28], "| body:", (r1.text or "")[:140].replace("\n", " "))
            # The gateway answers JSON with a text/javascript content-type; parse by content, not header.
            try:
                body1 = json.loads(r1.text or "")
            except ValueError:
                body1 = None
            if r1.status_code >= 400 or not isinstance(body1, dict):
                if r1.status_code in (404, 405) or "html" in ct:
                    print("  route not served here; trying next host")
                    continue
                break
            sid = str(body1.get("id", ""))
            print("  session id:", "upload:… ok" if sid.startswith("upload:") else "UNEXPECTED", "| len", len(sid))
            if not sid:
                break
            path, _, query = sid.partition("?")
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p) if query else None
            r2 = c.post(f"{base}/{ver}/{path}", params=params,
                        headers={**H, "file_offset": "0", "Content-Type": "image/png"}, content=PNG)
            print("  step2 POST /upload:<sid> ->", r2.status_code, "| body:", (r2.text or "")[:160].replace("\n", " "))
            h = ""
            try:
                body2 = json.loads(r2.text or "")
                h = str(body2.get("h", "")) if isinstance(body2, dict) else ""
            except ValueError:
                h = ""
            first = h.split("\n")[0] if h else ""
            print("  h handle:", "YES" if first else "NO", "| copies:", len(h.split("\n")) if h else 0, "| first len:", len(first), "| prefix:", first[:5])
            print("RESULT:", ("MINT_OK via " + base) if first else ("MINT_FAILED via " + base))
            break
    except Exception as e:  # noqa: BLE001 - a probe reports, it does not raise
        print("  error:", type(e).__name__, str(e)[:160])
print("PROBE_DONE")
