import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("catalog", "0002_wabanumber_label"),
        ("inbox", "0011_shared_asset_and_default_labels"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Campaign",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("done", "Done"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("variables", models.JSONField(blank=True, default=dict)),
                ("header_variables", models.JSONField(blank=True, default=dict)),
                ("button_variables", models.JSONField(blank=True, default=dict)),
                ("header_media_id", models.CharField(blank=True, max_length=255)),
                ("total", models.PositiveIntegerField(default=0)),
                ("sent", models.PositiveIntegerField(default=0)),
                ("failed", models.PositiveIntegerField(default=0)),
                ("skipped", models.PositiveIntegerField(default=0)),
                ("error_detail", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="campaigns",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "number",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="campaigns",
                        to="catalog.wabanumber",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="campaigns",
                        to="catalog.watemplate",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="CampaignRecipient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone", models.CharField(db_index=True, max_length=32)),
                ("name", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("owner_data_id", models.PositiveIntegerField(blank=True, null=True)),
                ("owner_data_created", models.BooleanField(default=False)),
                ("error_detail", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "campaign",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recipients",
                        to="campaigns.campaign",
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="inbox.conversation",
                    ),
                ),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="campaignrecipient",
            constraint=models.UniqueConstraint(fields=("campaign", "phone"), name="uniq_campaign_phone"),
        ),
    ]
