from django.db import migrations


# Cloud API + WhatsApp Business App (coexistence) WBX channels Alots listed.
# community marks them; empty agent labels get the Alots account name.
COEXISTENCE = (
    ("971563523109", "Dubai01WBX", "915527684966562", None),
    ("971559632895", "A7GroupWBX", "1248276241703985", None),
    ("971527514497", "Dubai02WBX", "1333970816455742", None),
    ("971558448678", "Dubai03WBX", "1225399537330522", None),
    ("971559791401", "Dubai04WBX", "1339159432604269", None),
    ("971525531548", "Dubai05WBX", "1192853460586165", None),
    ("971529312577", "Dubai06WBX", "1266282383224189", None),
    ("971507563104", "Dubai07WBX", "1114281478435734", None),
    ("971543752608", "Dubai08WBX", "194013153789312", None),
    ("971564821835", "Dubai09WBX", "1264060830128584", None),
    # 0008 typo 9589; live Alots webhooks use 9689
    ("971559783176", "Dubai10WBX", "1210894495449689", "1210894495449589"),
)


def apply_coexistence(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    for phone, account, live_pnid, old_pnid in COEXISTENCE:
        row = WabaNumber.objects.filter(phone_number=phone).first()
        if not row:
            continue
        fields = []
        if old_pnid and row.phone_number_id == old_pnid:
            if not WabaNumber.objects.filter(phone_number_id=live_pnid).exclude(pk=row.pk).exists():
                row.phone_number_id = live_pnid
                fields.append("phone_number_id")
        if row.community != "coexistence":
            row.community = "coexistence"
            fields.append("community")
        # Keep agent names (Abdul, Fozia, …); only fill blanks with WBX account.
        if not (row.label or "").strip():
            row.label = account
            fields.append("label")
        if not (row.display_name or "").strip():
            row.display_name = account
            fields.append("display_name")
        if phone == "971563523109" and not row.is_active:
            row.is_active = True
            fields.append("is_active")
        if fields:
            row.save(update_fields=fields)


def revert_coexistence(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    accounts = {phone: account for phone, account, *_ in COEXISTENCE}
    for phone, account, live_pnid, old_pnid in COEXISTENCE:
        row = WabaNumber.objects.filter(phone_number=phone).first()
        if not row:
            continue
        fields = []
        if row.community == "coexistence":
            row.community = ""
            fields.append("community")
        if row.label == account:
            row.label = ""
            fields.append("label")
        if row.display_name == account:
            row.display_name = ""
            fields.append("display_name")
        if old_pnid and row.phone_number_id == live_pnid:
            if not WabaNumber.objects.filter(phone_number_id=old_pnid).exclude(pk=row.pk).exists():
                row.phone_number_id = old_pnid
                fields.append("phone_number_id")
        if fields:
            row.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0009_watemplatehide"),
    ]

    operations = [
        migrations.RunPython(apply_coexistence, revert_coexistence),
    ]
