# Read-only: list Alots channels and mark which are already in catalog_wabanumber.
from apps.catalog.models import WabaNumber
from apps.gateway.client import AlotsClient

channels = AlotsClient().list_channels() or []
known_phone = {row.phone_number: row for row in WabaNumber.objects.all()}
known_pnid = {row.phone_number_id: row for row in WabaNumber.objects.all()}
print(f"channels={len(channels)} catalog={WabaNumber.objects.count()}")
if channels:
    print("sample keys:", sorted((channels[0] or {}).keys()))
    print("sample row:", channels[0])

missing = []
for ch in channels:
    phone = "".join(
        c
        for c in str(
            ch.get("wabaNumber")
            or ch.get("phone_number")
            or ch.get("display_phone_number")
            or ch.get("phoneNumber")
            or ""
        )
        if c.isdigit()
    )
    pnid = str(
        ch.get("phoneNumberId")
        or ch.get("phone_number_id")
        or ch.get("id")
        or ""
    ).strip()
    waba = str(
        ch.get("wabaBusinessId")
        or ch.get("waba_business_id")
        or ch.get("waba_id")
        or ""
    ).strip()
    name = str(
        ch.get("verified_name")
        or ch.get("display_name")
        or ch.get("displayName")
        or ch.get("name")
        or ""
    ).strip()
    row = known_phone.get(phone) or known_pnid.get(pnid)
    if row:
        flag = "IN_DB"
        if row.phone_number != phone or row.phone_number_id != pnid:
            flag = "MISMATCH"
        print(f"{flag}\t{phone}\t{pnid}\t{waba}\t{name or row.display_name}\tdb={row.phone_number}")
    else:
        print(f"MISSING\t{phone}\t{pnid}\t{waba}\t{name}")
        missing.append((phone, pnid, waba, name))

print("--- missing ---", len(missing))
for phone, pnid, waba, name in missing:
    print(f"ADD\t{phone}\t{pnid}\t{waba}\t{name}")
print("PROBE_OK")
