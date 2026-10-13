from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gateway", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PanelSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cookie", models.TextField(blank=True)),
                ("seed_fingerprint", models.CharField(blank=True, max_length=64)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("last_ok_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=300)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
