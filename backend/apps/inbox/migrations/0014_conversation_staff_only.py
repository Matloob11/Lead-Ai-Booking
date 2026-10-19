from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inbox", "0013_transfer_panel_copy"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="staff_only",
            field=models.BooleanField(default=False),
        ),
    ]
