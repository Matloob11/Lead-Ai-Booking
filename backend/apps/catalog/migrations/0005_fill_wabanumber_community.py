from django.db import migrations

# Official numbers whose assigned agent matched AGENTS DETAILS.pdf.
# Phone → PDF community. Muhammad Saeed / Nabiha / Sapna / Fakhra are not here.
MATCHED = {
    "971556059331": "Mudon Al Ranim",
    "971556354628": "Mudon Al Ranim",
    "971555716422": "Villa Nova",
    "971555832603": "Damac Lagoon, Costa Brava, Portfino",
    "971556082710": "Damac Lagoon, Malta, Santorini",
    "971555306149": "Arabian Ranchers 3",
    "971555956439": "Arabian Ranchers 3",
    "971555497521": "Arabian Ranchers 3",
    "971559193588": "The valley",
    "971556037342": "The valley",
    "971524492026": "International city",
    "971524077268": "International city",
    "971555817694": "International city",
    "971559632895": "International city",
    "971559477395": "International city",
    "971559430556": "International city",
    "971559668904": "Damac Hills 2",
    "971555850765": "Damac Hills 2",
    "971555689029": "Damac Hills 2",
    "971524473103": "Damac Hills 2",
    "971559481572": "Damac Hills 2",
}


def fill_number_communities(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    for phone, community in MATCHED.items():
        updated = WabaNumber.objects.filter(phone_number=phone).update(community=community)
        if not updated:
            WabaNumber.objects.filter(phone_number=f"+{phone}").update(community=community)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_wabanumber_community"),
    ]

    operations = [
        migrations.RunPython(fill_number_communities, noop_reverse),
    ]
