"""Insert Dubai10WBX + two extra Official numbers into catalog (idempotent)."""

from apps.catalog.models import WabaNumber

NUMBERS = (
    ("971559783176", "1210894495449589", "1598838648533479", "Fameeda"),
    ("447723374770", "1228783236981996", "3667658976733043", "Sapphire Grove Estates"),
    ("447723351148", "115860127227627", "1020414087303484", "Tranquil Crest Villas"),
    ("447723608460", "1235220126336307", "1793409055019513", "Luxe Towers Realty"),
    ("447723474991", "1297886426732238", "1548675563673216", "Grand Park Real Estate"),
    ("447723545003", "1293126193878094", "2272382243298169", "Haven Square"),
    ("447723321328", "1277112012142361", "1535123498115022", "Luxe Towers Realty"),
    ("447723185014", "1165855536620650", "2031773307431673", "Eminence Estates"),
    ("447723356623", "1224845880710307", "1423593616270383", "Horizon Crest"),
    ("447723011791", "1245341881987034", "2002634827104766", "Horizon Crest Residences"),
    ("447723448895", "1203159729544610", "1048905584241267", "Elysian Grove Estates"),
    ("971564821835", "1264060830128584", "1482404467251874", "Real Estate Consultant"),
    ("971543752608", "194013153789312", "186442104552377", "kanwal"),
)

created = 0
skipped = 0
for phone, pnid, waba, name in NUMBERS:
    existing = (
        WabaNumber.objects.filter(phone_number=phone).first()
        or WabaNumber.objects.filter(phone_number_id=pnid).first()
    )
    if existing:
        skipped += 1
        print(f"skip {phone} existing_id={existing.pk}", flush=True)
        continue
    WabaNumber.objects.create(
        phone_number=phone,
        phone_number_id=pnid,
        waba_business_id=waba,
        display_name=name,
        label=name,
        source=WabaNumber.Source.MANUAL,
        is_active=True,
        webhook_configured=False,
    )
    created += 1
    print(f"created {phone} {name}", flush=True)

print(f"done created={created} skipped={skipped}", flush=True)
print(
    "webhook_url=https://wa.srv1802669.hstgr.cloud/api/gateway/webhook/alots/",
    flush=True,
)
