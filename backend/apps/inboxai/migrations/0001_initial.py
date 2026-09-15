import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("inbox", "0011_shared_asset_and_default_labels"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentAiDesk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                (
                    "scope",
                    models.CharField(
                        choices=[
                            ("off", "Off"),
                            ("new", "New chats"),
                            ("all", "All my chats"),
                            ("selected", "Selected chats"),
                        ],
                        default="off",
                        max_length=16,
                    ),
                ),
                ("context", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "agent",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_desk",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "selected",
                    models.ManyToManyField(blank=True, related_name="+", to="inbox.conversation"),
                ),
            ],
            options={
                "verbose_name": "AI desk",
                "verbose_name_plural": "AI desks",
            },
        ),
        migrations.CreateModel(
            name="ConversationAiCover",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                ("context", models.TextField(blank=True)),
                ("paused_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "agent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_covers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "conversation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_cover",
                        to="inbox.conversation",
                    ),
                ),
            ],
            options={
                "verbose_name": "conversation AI cover",
                "verbose_name_plural": "conversation AI covers",
            },
        ),
    ]
