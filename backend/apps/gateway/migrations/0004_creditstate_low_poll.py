from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gateway", "0003_creditstate"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditstate",
            name="low",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="creditstate",
            name="poll_failures",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="creditstate",
            name="low_warned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
