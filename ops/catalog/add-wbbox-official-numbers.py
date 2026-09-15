# Idempotent insert of WBBOX Official API channels into catalog_wabanumber.
# Manual source so gateway sync does not deactivate them. Does not touch Linked phones.
# Does not store or print any API key.

from apps.catalog.models import WabaNumber

ROWS = [
    {
        "phone_number": "971563523109",
        "phone_number_id": "915527684966562",
        "waba_business_id": "2026067364835660",
        "display_name": "Property Market",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "NOT_VERIFIED",
        "messaging_limit": "TIER_250",
    },
    {
        "phone_number": "447414120776",
        "phone_number_id": "850871391441260",
        "waba_business_id": "1221254273173301",
        "display_name": "Amara Estates",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447882967787",
        "phone_number_id": "799916463212123",
        "waba_business_id": "1474625567103583",
        "display_name": "Blue Horizon Estates",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447882963471",
        "phone_number_id": "846913318509780",
        "waba_business_id": "1552100039544930",
        "display_name": "Imperial Crest Realty",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447479325117",
        "phone_number_id": "851109151421354",
        "waba_business_id": "863270339714197",
        "display_name": "Coastline Properties",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_10K",
    },
    {
        "phone_number": "447846864137",
        "phone_number_id": "838433426021032",
        "waba_business_id": "25393299086934645",
        "display_name": "Serene Tax",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447480785539",
        "phone_number_id": "839330929266637",
        "waba_business_id": "1190668849575881",
        "display_name": "CleanSlate Web Solutions",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447480775697",
        "phone_number_id": "873354545858663",
        "waba_business_id": "1505334140729890",
        "display_name": "Black Palace Real Estate",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447476951819",
        "phone_number_id": "904232262762762",
        "waba_business_id": "1974895426700573",
        "display_name": "Grandeur Harmony Realty",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447476963121",
        "phone_number_id": "796222643582259",
        "waba_business_id": "1314287423312849",
        "display_name": "Grandeur Harmony",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447727759813",
        "phone_number_id": "894661730388892",
        "waba_business_id": "826273936717177",
        "display_name": "Black Palace",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447476959465",
        "phone_number_id": "882010554992565",
        "waba_business_id": "1350079783461684",
        "display_name": "CleanSlate",
        "quality_rating": WabaNumber.Quality.HIGH,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447476545324",
        "phone_number_id": "820455261158530",
        "waba_business_id": "590280834144534",
        "display_name": "Luxury Properties",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447456440254",
        "phone_number_id": "836240229575100",
        "waba_business_id": "1860187135382549",
        "display_name": "Crux Real Estate",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447360541180",
        "phone_number_id": "884067921448856",
        "waba_business_id": "1240446191462251",
        "display_name": "Regal Peaks",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
    {
        "phone_number": "447481338761",
        "phone_number_id": "828209983713062",
        "waba_business_id": "1446666826427407",
        "display_name": "Splendid Aura Homes",
        "quality_rating": WabaNumber.Quality.UNKNOWN,
        "verification_status": "EXPIRED",
        "messaging_limit": "TIER_2K",
    },
]

created = 0
skipped = 0
for row in ROWS:
    taken = WabaNumber.objects.filter(phone_number_id=row["phone_number_id"]).first()
    if taken is None:
        taken = WabaNumber.objects.filter(phone_number=row["phone_number"]).first()
    if taken is not None:
        print("skip", row["phone_number"], row["display_name"])
        skipped += 1
        continue
    WabaNumber.objects.create(
        phone_number=row["phone_number"],
        phone_number_id=row["phone_number_id"],
        waba_business_id=row["waba_business_id"],
        display_name=row["display_name"],
        label=row["display_name"],
        community="",
        quality_rating=row["quality_rating"],
        verification_status=row["verification_status"],
        messaging_limit=row["messaging_limit"],
        source=WabaNumber.Source.MANUAL,
        is_active=True,
        webhook_configured=False,
        synced_at=None,
    )
    print("created", row["phone_number"], row["display_name"])
    created += 1

print("created_count", created)
print("skipped_count", skipped)
print("expected_new", len(ROWS))
print("active_total", WabaNumber.objects.filter(is_active=True).count())
print("manual_total", WabaNumber.objects.filter(source=WabaNumber.Source.MANUAL).count())
