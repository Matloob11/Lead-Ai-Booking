from django.db import migrations


NUMBERS = (
    {
        "phone_number": "971559783176",
        "phone_number_id": "1210894495449589",
        "waba_business_id": "1598838648533479",
        "display_name": "Fameeda",
        "label": "Fameeda",
    },
    {
        "phone_number": "447723374770",
        "phone_number_id": "1228783236981996",
        "waba_business_id": "3667658976733043",
        "display_name": "Sapphire Grove Estates",
        "label": "Sapphire Grove Estates",
    },
    {
        "phone_number": "447723351148",
        "phone_number_id": "115860127227627",
        "waba_business_id": "1020414087303484",
        "display_name": "Tranquil Crest Villas",
        "label": "Tranquil Crest Villas",
    },
    {
        "phone_number": "447723608460",
        "phone_number_id": "1235220126336307",
        "waba_business_id": "1793409055019513",
        "display_name": "Luxe Towers Realty",
        "label": "Luxe Towers Realty",
    },
    {
        "phone_number": "447723474991",
        "phone_number_id": "1297886426732238",
        "waba_business_id": "1548675563673216",
        "display_name": "Grand Park Real Estate",
        "label": "Grand Park Real Estate",
    },
    {
        "phone_number": "447723545003",
        "phone_number_id": "1293126193878094",
        "waba_business_id": "2272382243298169",
        "display_name": "Haven Square",
        "label": "Haven Square",
    },
    {
        "phone_number": "447723321328",
        "phone_number_id": "1277112012142361",
        "waba_business_id": "1535123498115022",
        "display_name": "Luxe Towers Realty",
        "label": "Luxe Towers Realty",
    },
    {
        "phone_number": "447723185014",
        "phone_number_id": "1165855536620650",
        "waba_business_id": "2031773307431673",
        "display_name": "Eminence Estates",
        "label": "Eminence Estates",
    },
    {
        "phone_number": "447723356623",
        "phone_number_id": "1224845880710307",
        "waba_business_id": "1423593616270383",
        "display_name": "Horizon Crest",
        "label": "Horizon Crest",
    },
    {
        "phone_number": "447723011791",
        "phone_number_id": "1245341881987034",
        "waba_business_id": "2002634827104766",
        "display_name": "Horizon Crest Residences",
        "label": "Horizon Crest Residences",
    },
    {
        "phone_number": "447723448895",
        "phone_number_id": "1203159729544610",
        "waba_business_id": "1048905584241267",
        "display_name": "Elysian Grove Estates",
        "label": "Elysian Grove Estates",
    },
    {
        "phone_number": "971564821835",
        "phone_number_id": "1264060830128584",
        "waba_business_id": "1482404467251874",
        "display_name": "Real Estate Consultant",
        "label": "Real Estate Consultant",
    },
    {
        "phone_number": "971543752608",
        "phone_number_id": "194013153789312",
        "waba_business_id": "186442104552377",
        "display_name": "kanwal",
        "label": "kanwal",
    },
)


def add_numbers(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    for row in NUMBERS:
        existing = (
            WabaNumber.objects.filter(phone_number=row["phone_number"]).first()
            or WabaNumber.objects.filter(phone_number_id=row["phone_number_id"]).first()
        )
        if existing:
            continue
        WabaNumber.objects.create(
            phone_number=row["phone_number"],
            phone_number_id=row["phone_number_id"],
            waba_business_id=row["waba_business_id"],
            display_name=row["display_name"],
            label=row["label"],
            source="manual",
            is_active=True,
            webhook_configured=False,
        )


def remove_numbers(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    WabaNumber.objects.filter(
        phone_number_id__in=[row["phone_number_id"] for row in NUMBERS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0007_fix_abdul_phone_number_id"),
    ]

    operations = [
        migrations.RunPython(add_numbers, remove_numbers),
    ]
