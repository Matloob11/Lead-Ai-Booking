# Probe: list gateway channels and diff vs catalog (no writes).
from apps.catalog.models import WabaNumber
from apps.gateway.client import AlotsClient

channels = AlotsClient().list_channels()
print("gateway_channels", len(channels))
known_pnid = set(WabaNumber.objects.values_list("phone_number_id", flat=True))
known_phone = set(WabaNumber.objects.values_list("phone_number", flat=True))
missing = []
for ch in channels:
    phone = str(ch.get("wabaNumber") or "").lstrip("+")
    pnid = str(ch.get("phoneNumberId") or "")
    waba = str(ch.get("wabaBusinessId") or "")
    name = str(ch.get("displayName") or ch.get("verifiedName") or "")
    in_pnid = pnid in known_pnid
    in_phone = phone in known_phone
    flag = "OK" if in_pnid else ("PHONE_ONLY" if in_phone else "MISSING")
    print(flag, phone, pnid, waba, name)
    if flag != "OK":
        missing.append((phone, pnid, waba, name, flag))
print("missing_or_mismatch", len(missing))
for row in missing:
    print("NEED", row[0], row[1], row[2], row[3], row[4])
