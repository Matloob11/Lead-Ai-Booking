from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("catalog", "0012_wabanumber_template_sync_error"),
        ("inbox", "0013_transfer_panel_copy"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LeadAutomation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bitrix_lead_id", models.PositiveIntegerField(db_index=True, unique=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("awaiting_reply", "Awaiting reply"),
                            ("active", "AI qualifying"),
                            ("qualified", "Qualified"),
                            ("junk", "Junk / opt-out"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("customer_phone", models.CharField(blank=True, default="", max_length=32)),
                ("outreach_template_name", models.CharField(blank=True, default="", max_length=128)),
                ("outreach_message_id", models.CharField(blank=True, default="", max_length=128)),
                ("last_error", models.TextField(blank=True, default="")),
                ("snapshot", models.JSONField(blank=True, default=dict)),
                ("confirmed_fields", models.JSONField(blank=True, default=dict)),
                ("qualification_reason", models.CharField(blank=True, default="", max_length=255)),
                ("qualified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "agent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="lead_automations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="lead_automations",
                        to="inbox.conversation",
                    ),
                ),
                (
                    "number",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="lead_automations",
                        to="catalog.wabanumber",
                    ),
                ),
            ],
            options={"ordering": ["-id"]},
        ),
    ]
