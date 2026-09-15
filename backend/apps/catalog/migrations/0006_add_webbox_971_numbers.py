from django.db import migrations


NUMBERS = (
    {
        "phone_number": "971529312577",
        "phone_number_id": "1266282393224189",
        "waba_business_id": "2037888833780534",
        "display_name": "Abdul",
        "label": "Abdul",
    },
    {
        "phone_number": "971507563104",
        "phone_number_id": "1114281478435734",
        "waba_business_id": "1480015549993522",
        "display_name": "Property Consultant",
        "label": "Property Consultant",
    },
)


def add_numbers(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    for row in NUMBERS:
        existing = WabaNumber.objects.filter(
            phone_number=row["phone_number"]
        ).first() or WabaNumber.objects.filter(phone_number_id=row["phone_number_id"]).first()
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
        ("catalog", "0005_fill_wabanumber_community"),
    ]

    operations = [
        migrations.RunPython(add_numbers, remove_numbers),
    ]
