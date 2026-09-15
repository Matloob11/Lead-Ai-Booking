from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0011_wabanumber_account_username"),
    ]

    operations = [
        migrations.AddField(
            model_name="wabanumber",
            name="template_sync_error",
            field=models.CharField(blank=True, max_length=300),
        ),
    ]
