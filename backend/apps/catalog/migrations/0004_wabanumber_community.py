from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_wabanumber_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="wabanumber",
            name="community",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
