from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0002_campaign_retry"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaignrecipient",
            name="variables",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
