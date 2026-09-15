from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inboxai", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationHealth",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("colour", models.CharField(blank=True, default="", max_length=16)),
                ("colour_locked", models.BooleanField(default=False)),
                ("reason", models.TextField(blank=True)),
                ("flags", models.JSONField(blank=True, default=list)),
                ("confidence", models.FloatField(default=0)),
                ("needs_human_review", models.BooleanField(default=False)),
                ("message_count_since_classify", models.PositiveIntegerField(default=0)),
                ("last_classified_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "conversation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_health",
                        to="inbox.conversation",
                    ),
                ),
            ],
            options={
                "verbose_name": "conversation health",
                "verbose_name_plural": "conversation health",
            },
        ),
        migrations.AddIndex(
            model_name="conversationhealth",
            index=models.Index(fields=["colour"], name="inboxai_health_colour"),
        ),
    ]
