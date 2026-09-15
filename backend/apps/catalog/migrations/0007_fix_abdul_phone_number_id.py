from django.db import migrations


OLD_ID = "1266282393224189"
LIVE_ID = "1266282383224189"
PHONE = "971529312577"


def fix_phone_number_id(apps, schema_editor):
    """0006 stored a typo. Live Alots webhooks use LIVE_ID."""
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    if WabaNumber.objects.filter(phone_number_id=LIVE_ID).exclude(phone_number=PHONE).exists():
        return
    WabaNumber.objects.filter(phone_number=PHONE, phone_number_id=OLD_ID).update(
        phone_number_id=LIVE_ID
    )


def revert_phone_number_id(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    if WabaNumber.objects.filter(phone_number_id=OLD_ID).exists():
        return
    WabaNumber.objects.filter(phone_number=PHONE, phone_number_id=LIVE_ID).update(
        phone_number_id=OLD_ID
    )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_add_webbox_971_numbers"),
    ]

    operations = [
        migrations.RunPython(fix_phone_number_id, revert_phone_number_id),
    ]
