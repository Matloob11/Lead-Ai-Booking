from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0005_campaignbatch"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaignrecipient",
            name="crm_deal_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="campaignrecipient",
            name="crm_role",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
    ]
