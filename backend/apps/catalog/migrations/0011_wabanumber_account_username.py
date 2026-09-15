from django.db import migrations, models


# Dubai Waba Number details sheet (gid 2080113227), column Username.
# Plus two deactivated extras that still sit in the catalog.
SHEET_USERNAMES = {
    "447360267436": "Dubai11WBX",
    "447360545726": "Dubai02WBX",
    "447361590663": "Dubai02WBX",
    "447366360875": "Dubai02WBX",
    "447401457395": "Dubai02WBX",
    "447414115945": "Dubai07WBX",
    "447414121510": "Dubai07WBX",
    "447414128143": "Dubai07WBX",
    "447414131370": "Dubai07WBX",
    "447426758743": "Dubai03WBX",
    "447426912372": "Dubai03WBX",
    "447426961172": "Dubai03WBX",
    "447427924701": "Dubai03WBX",
    "447428322124": "Dubai02WBX",
    "447447178015": "Dubai03WBX",
    "447447179547": "Dubai04WBX",
    "447447184236": "Dubai03WBX",
    "447447187245": "Dubai03WBX",
    "447455749638": "Dubai04WBX",
    "447462178442": "Dubai11WBX",
    "447462536357": "Dubai11WBX",
    "447462539765": "Dubai04WBX",
    "447463947958": "Dubai11WBX",
    "447476928266": "Dubai02WBX",
    "447476957698": "Dubai11WBX",
    "447476959465": "Dubai01WBX",
    "447476987129": "Dubai02WBX",
    "447476992120": "Dubai06WBX",
    "447476993013": "Dubai05WBX",
    "447476993627": "Dubai05WBX",
    "447476994353": "Dubai05WBX",
    "447476994508": "Dubai05WBX",
    "447476994670": "Dubai05WBX",
    "447476994839": "Dubai05WBX",
    "447576534429": "Dubai11WBX",
    "447723011791": "Dubai10WBX",
    "447723185014": "Dubai10WBX",
    "447723185187": "Dubai11WBX",
    "447723186020": "Dubai11WBX",
    "447723321328": "Dubai10WBX",
    "447723325193": "Dubai11WBX",
    "447723351149": "Dubai10WBX",
    "447723356623": "Dubai10WBX",
    "447723374770": "Dubai10WBX",
    "447723430080": "Dubai04WBX",
    "447723448895": "Dubai10WBX",
    "447723458662": "Dubai11WBX",
    "447723461484": "Dubai11WBX",
    "447723474991": "Dubai10WBX",
    "447723495849": "Dubai11WBX",
    "447723504881": "Dubai11WBX",
    "447723545003": "Dubai10WBX",
    "447723576678": "Dubai11WBX",
    "447723608460": "Dubai10WBX",
    "447727624256": "Dubai04WBX",
    "447735852054": "Dubai04WBX",
    "447782361546": "Dubai05WBX",
    "447782639429": "Dubai03WBX",
    "447828569383": "Dubai05WBX",
    "447830355926": "Dubai03WBX",
    "447846855263": "Dubai04WBX",
    "447846870802": "Dubai04WBX",
    "447846888462": "Dubai04WBX",
    "447882968294": "Dubai04WBX",
    "971507563104": "Dubai07WBX",
    "971524077268": "A7GroupWBX",
    "971524473103": "A7GroupWBX",
    "971524492026": "A7GroupWBX",
    "971525531548": "Dubai05WBX",
    "971527514497": "Dubai02WBX",
    "971529312577": "Dubai06WBX",
    "971543752608": "Dubai08WBX",
    "971555306149": "A7GroupWBX",
    "971555497521": "A7GroupWBX",
    "971555689029": "A7GroupWBX",
    "971555716422": "A7GroupWBX",
    "971555817694": "A7GroupWBX",
    "971555832603": "A7GroupWBX",
    "971555850765": "A7GroupWBX",
    "971555956439": "A7GroupWBX",
    "971556037342": "A7GroupWBX",
    "971556059331": "A7GroupWBX",
    "971556082710": "A7GroupWBX",
    "971556354628": "A7GroupWBX",
    "971556441831": "A7GroupWBX",
    "971556748730": "A7GroupWBX",
    "971556829046": "A7GroupWBX",
    "971557327268": "A7GroupWBX",
    "971557466914": "A7GroupWBX",
    "971558448678": "Dubai03WBX",
    "971559193588": "A7GroupWBX",
    "971559430556": "A7GroupWBX",
    "971559477395": "A7GroupWBX",
    "971559481572": "A7GroupWBX",
    "971559632895": "A7GroupWBX",
    "971559668904": "A7GroupWBX",
    "971559759052": "Dubai10WBX",
    "971559783176": "Dubai10WBX",
    "971559791401": "Dubai04WBX",
    "971563523109": "Dubai01WBX",
    "971564821835": "Dubai09WBX",
}


def fill_usernames(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    for phone, username in SHEET_USERNAMES.items():
        updated = WabaNumber.objects.filter(phone_number=phone).update(account_username=username)
        if not updated:
            WabaNumber.objects.filter(phone_number=f"+{phone}").update(account_username=username)


def clear_usernames(apps, schema_editor):
    WabaNumber = apps.get_model("catalog", "WabaNumber")
    WabaNumber.objects.exclude(account_username="").update(account_username="")


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0010_coexistence_wbx_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="wabanumber",
            name="account_username",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.RunPython(fill_usernames, clear_usernames),
    ]
