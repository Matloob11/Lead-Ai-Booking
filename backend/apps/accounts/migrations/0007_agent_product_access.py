from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_openwaassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="can_official_api",
            field=models.BooleanField(
                default=True, help_text="May use the Official API (Cloud) inbox"
            ),
        ),
        migrations.AddField(
            model_name="agent",
            name="can_linked_devices",
            field=models.BooleanField(
                default=True, help_text="May open Linked phones (OpenWA)"
            ),
        ),
    ]
