# Add the remaining UAE (971) numbers from WBBOX profiles 2–5.
# A7GroupWBX sync numbers and already-added 971559759052 are skipped.

from apps.catalog.models import WabaNumber

ADD = [
    ("971527514497", "1333970816455742", "2273706523459001"),  # Dubai02 Shahid Nawab
    ("971558448678", "1225399537330522", "2081490632745113"),  # Dubai03 Neha
    ("971559791401", "1339159432604269", "1369618845050157"),  # Dubai04 khan
    ("971525531548", "1192853460586165", "1718462712799238"),  # Dubai05 real esate
]

sync_before = WabaNumber.objects.filter(source=WabaNumber.Source.SYNC, is_active=True).count()
print("sync_active_before", sync_before)
created = 0
skipped = 0
for phone, pnid, waba in ADD:
    clash = WabaNumber.objects.filter(phone_number_id=pnid).first() or WabaNumber.objects.filter(
        phone_number=phone
    ).first()
    if clash is not None:
        if clash.source == WabaNumber.Source.SYNC:
            print("skip_sync", phone)
        else:
            print("skip_exists", phone, "active" if clash.is_active else "inactive")
        skipped += 1
        continue
    WabaNumber.objects.create(
        phone_number=phone,
        phone_number_id=pnid,
        waba_business_id=waba,
        display_name="",
        label="",
        community="",
        quality_rating=WabaNumber.Quality.UNKNOWN,
        verification_status="",
        messaging_limit="",
        source=WabaNumber.Source.MANUAL,
        is_active=True,
        webhook_configured=False,
        synced_at=None,
    )
    print("created", phone)
    created += 1

sync_after = WabaNumber.objects.filter(source=WabaNumber.Source.SYNC, is_active=True).count()
print("created_count", created)
print("skipped_count", skipped)
print("sync_active_after", sync_after)
print("uae_active", WabaNumber.objects.filter(is_active=True, phone_number__startswith="971").count())
print("active_total", WabaNumber.objects.filter(is_active=True).count())
for phone, _, _ in ADD:
    row = WabaNumber.objects.get(phone_number=phone)
    print("ok", phone, "active" if row.is_active else "inactive", row.source)
