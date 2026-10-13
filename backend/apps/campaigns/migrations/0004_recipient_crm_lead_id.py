from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0003_recipient_variables"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaignrecipient",
            name="crm_lead_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
