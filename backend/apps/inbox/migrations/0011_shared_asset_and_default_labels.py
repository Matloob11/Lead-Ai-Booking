from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_default_labels(apps, schema_editor):
    Label = apps.get_model("inbox", "Label")
    defaults = [
        ("Hot Lead", "#ef4444"),
        ("VIP Buyer", "#8b5cf6"),
        ("Follow-up Needed", "#f59e0b"),
        ("Site Visit", "#3b82f6"),
        ("Closed", "#10b981"),
    ]
    for name, colour in defaults:
        Label.objects.get_or_create(name=name, defaults={"colour": colour})


def reverse_labels(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("inbox", "0010_mediaasset_fallback_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("kind", models.CharField(choices=[("image", "Image"), ("document", "Document"), ("video", "Video")], default="document", max_length=16)),
                ("file", models.FileField(upload_to="shared/%Y/%m/")),
                ("file_name", models.CharField(blank=True, max_length=255)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("mime_type", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(seed_default_labels, reverse_labels),
    ]
