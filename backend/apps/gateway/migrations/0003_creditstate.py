from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gateway", "0002_panelsession"),
    ]

    operations = [
        migrations.CreateModel(
            name="CreditState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("out", models.BooleanField(default=False)),
                ("balance", models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ("warned_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "credit state",
            },
        ),
    ]
