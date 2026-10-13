import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0004_recipient_crm_lead_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CampaignBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=200)),
                ("template_name", models.CharField(max_length=255)),
                ("template_language", models.CharField(blank=True, max_length=16)),
                ("source_filename", models.CharField(blank=True, max_length=255)),
                ("column_map", models.JSONField(blank=True, default=dict)),
                ("per_number_cap", models.PositiveIntegerField(default=300)),
                (
                    "crm_target",
                    models.CharField(
                        choices=[
                            ("none", "No CRM card"),
                            ("owner_data", "Owner Data (calling board)"),
                            ("availability", "Availability"),
                        ],
                        default="none",
                        max_length=16,
                    ),
                ),
                ("total", models.PositiveIntegerField(default=0)),
                ("leftover", models.PositiveIntegerField(default=0)),
                ("skipped_numbers", models.JSONField(blank=True, default=list)),
                ("warnings", models.JSONField(blank=True, default=list)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="campaign_batches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="campaign",
            name="batch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="campaigns",
                to="campaigns.campaignbatch",
            ),
        ),
        migrations.AddField(
            model_name="campaign",
            name="crm_target",
            field=models.CharField(
                blank=True,
                choices=[
                    ("none", "No CRM card"),
                    ("owner_data", "Owner Data (calling board)"),
                    ("availability", "Availability"),
                ],
                default="",
                max_length=16,
            ),
        ),
    ]
