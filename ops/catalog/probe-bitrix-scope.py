# Run through `ops/wa.sh probe-bitrix-scope`: lists the permission scopes of the
# Bitrix webhook the WhatsApp backend uses (BITRIX_WEBHOOK_URL), so we know
# whether it may send Bitrix notifications (scope "im"). Read-only: the REST
# method "scope" changes nothing. Never prints the webhook URL or its token.
from apps.crmlink import client

try:
    scopes = client.call("scope", {}) or []
    print("scopes=" + ",".join(sorted(str(s) for s in scopes)))
    print("has_im=" + ("yes" if "im" in scopes else "no"))
    print("has_crm=" + ("yes" if "crm" in scopes else "no"))
except client.BitrixError as exc:
    print("error=" + str(exc)[:200])
print("PROBE_OK")
