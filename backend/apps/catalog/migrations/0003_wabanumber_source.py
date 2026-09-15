from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_wabanumber_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="wabanumber",
            name="source",
            field=models.CharField(
                choices=[("sync", "Synced from gateway"), ("manual", "Added manually")],
                db_index=True,
                default="sync",
                max_length=16,
            ),
        ),
    ]
