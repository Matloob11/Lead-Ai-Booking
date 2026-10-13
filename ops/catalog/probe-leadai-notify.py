# Run through `ops/wa.sh probe-leadai-notify`: the Bitrix side of the Lead AI
# alerts, end to end, from the live web container to the live Bitrix tool
# (bitrix/tools/a7_leadai_notify.php). Sends ONE notification, to Bitrix user
# 2311 only (the owner's own account), titled as a test; the same tag sent
# again must come back as a duplicate, so no second notification. Then checks
# that the tool refuses a wrong signature, no signature, an old timestamp and
# a GET. Prints the tool's answers; never the secret.
import json
import time

import httpx
from django.conf import settings

from apps.leadai.assistant import alerts

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


endpoint = settings.LEADAI_BITRIX_NOTIFY_URL
secret = (settings.CRM_LEAD_WA_SECRET or "").strip()
print("endpoint:", endpoint)
check("secret configured", bool(secret))
tag = f"LEADAI|probe|{int(time.time())}"
first = alerts.notify_bitrix(
    to_user_id=2311,
    title="Lead AI test (please ignore)",
    message="A test of the Lead AI alert path, sent by the deploy check. No customer is involved.",
    push="Lead AI test (please ignore)",
    tag=tag,
    url="/marketplace/app/76/",
)
print("signed:", first)
check("a signed notification is accepted", first.get("ok") is True and first.get("id"), first)
again = alerts.notify_bitrix(
    to_user_id=2311, title="Lead AI test (please ignore)", message="duplicate", push="duplicate", tag=tag, url=""
)
print("same tag again:", again)
check("the same tag again is a duplicate, not a second notification", again.get("duplicate") is True, again)

raw = json.dumps({"to_user_id": 2311, "title": "x", "message": "x", "tag": "", "url": ""}, separators=(",", ":")).encode()
now = str(int(time.time()))
plain = {"Content-Type": "application/json"}
r = httpx.post(endpoint, content=raw, headers={**plain, "X-Leadai-Ts": now, "X-Leadai-Sign": "0" * 64}, timeout=15)
check("a wrong signature is refused", r.status_code == 401, r.status_code)
r = httpx.post(endpoint, content=raw, headers=plain, timeout=15)
check("no signature is refused", r.status_code == 401, r.status_code)
old = str(int(time.time()) - 3600)
r = httpx.post(endpoint, content=raw, headers={**plain, "X-Leadai-Ts": old, "X-Leadai-Sign": alerts.sign(raw, old, secret)}, timeout=15)
check("an hour-old signature is refused", r.status_code == 401, r.status_code)
r = httpx.get(endpoint, timeout=15)
check("a GET is refused", r.status_code == 405, r.status_code)

for ok, name, detail in results:
    print("PASS" if ok else "FAIL", "|", name, "" if ok else f"| {detail}")
print("passed", sum(1 for ok, _, _ in results if ok), "of", len(results))
print("PROBE_OK")
